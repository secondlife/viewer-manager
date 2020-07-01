#!/usr/bin/python
"""\
@file   leapcomm.py
@author Nat Goodspeed
@date   2018-10-01
@brief  Protocol wrapper around low-level LEAP communications with the viewer.
        This layer interprets the inherently asynchronous, simplex event-based
        packets on stdin and stdout as requests and responses.

$LicenseInfo:firstyear=2018&license=viewerlgpl$
Copyright (c) 2018, Linden Research, Inc.
$/LicenseInfo$
"""

# n.b. This module is derived from vita.viewerclient.

from collections import namedtuple
import itertools
import time
import weakref

import eventlet

import leap
from leap import ProtocolError, ViewerShutdown, ParseError
from util import SL_Logging

class TimeoutError(Exception):
    pass

class ViewerWontShutdown(Exception):
    pass

class ViewerClient(object):
    """
    This class aggregates the data needed to track pending requests and match
    them with incoming replies.

    Should it become useful to use some other communications mechanism than
    LEAP (stdin, stdout), a subclass could override send() and get().
    """
    State = namedtuple("State", ("enum", "str"))

    def __init__(self):
        """
        Set up housekeeping.
        """
        # Read initialization data from viewer.
        leap.__init__()
        # If that worked, we're connected.
        self.connected = True

        self.log = SL_Logging.getLogger("ViewerClient")
        # To handle unsolicited packets arriving from the viewer, we give raw leap
        # input an eventlet coroutine of its own. (Requests are sent out
        # synchronously by the calling coroutine -- we don't have a problem with a
        # request blocking if the socket send() call blocks.)
        eventlet.spawn_n(self._receive)
        # Each outstanding request() or generate() call has a corresponding
        # WaitForReqid object (later in this module) to handle the
        # response(s). If an incoming event contains an echoed ["reqid"] key,
        # we can look up the appropriate WaitForReqid object more efficiently
        # in a dict than by tossing such objects into the usual waitfors list.
        # Note: the ["reqid"] must be unique, otherwise we could end up
        # replacing an earlier WaitForReqid object in self.pending with a
        # later one. That means that no incoming event will ever be given to
        # the old WaitForReqid object. Any coroutine waiting on the discarded
        # WaitForReqid object would therefore wait forever.
        self.pending = {}
        # Our consumer will instantiate some number of WaitFor subclass objects.
        # As these are traversed in descending priority order, we must keep
        # them in a list.
        self.waitfors = []
        # It has been suggested that we should use UUIDs as ["reqid"] values,
        # since UUIDs are guaranteed unique. However, as the "namespace" for
        # ["reqid"] values is a single viewer LEAP session, we can get away with
        # an LLSD::Integer -- unless we exceed 31 bits' worth of requests in a
        # single session.
        self.reqid = itertools.count()
        # Track the viewer's startup state, specifically so we can detect
        # whether the user has already clicked Login.
        self.startup_state = self.State(0, "")

        # Hook on a WaitForStartup instance to monitor StartupState
        # changes. In addition to supporting our waitForState() method, this
        # also implicitly updates startup_state every time an event arrives.
        startup_pump = "StartupState"

        self.startupWait = WaitForStartup(self, 0, startup_pump)
        # Listen for StartupState events. The listener at self.cmdpump() will
        # provide a response, so use self.request().
        self.request(pump=self.cmdpump(), data=dict(op="listen", source=startup_pump,
                                                    listener="ViewerClient"))

        # Poke LLStartUp to make sure we get an event even if we're already in
        # STATE_STARTED -- otherwise we could wait for a long time.
        self.send(pump="LLStartUp", data=dict(op="postStartupState"))

    # Override any of these next five methods to change the communication
    # mechanism.
    cmdpump   = staticmethod(leap.cmdpump)
    replypump = staticmethod(leap.replypump)
    get       = staticmethod(leap.get)

    def close(self):
        # LEAP uses sys.stdin and sys.stdout. While it's possible to close
        # them, there seems little point.
        pass

    def send(self, pump, data):
        """
        Fire and forget. Send the specified request LLSD, expecting no reply.
        In fact, should the request produce an eventual reply, it will be
        treated as an unsolicited event.

        See also request(), generate().
        """
        # leap.request() is a bit of a misnomer; it's only at this layer that
        # we try to match requests with responses. What leap.request() does
        # over and above leap.send() is to stamp the outgoing data with our
        # reply pump. No reason not to do that for every event.
        leap.request(pump, data)

    def get_startup_state(self):
        self.log.debug("yielding to pick up StartupState events")
        # Empirically, eventlet.sleep(0) does NOT suffice here, though that's
        # the canonical way to yield to other eventlet greenthreads. This may
        # be due to the use of eventlet.tpool.Proxy (in other words, an actual
        # separate Python thread) for sys.stdin. While sleep(0.1) also seems
        # to work, the need for ANY actual real-time delay makes me nervous
        # about the robustness of making it too short. Stick with 0.5 for now;
        # should still be imperceptible from the user's point of view.
        eventlet.sleep(0.5)
        return self.startup_state

    def shutdown(self):
        """
        Send event to ask the viewer to shutdown nicely. Raise
        ViewerWontShutdown if it doesn't seem to respond to the request.
        """
        # Permit multiple calls without ill effect.
        if not self.connected:
            self.log.debug("viewer already shut down")
            return
        # Send the request. We used to use the "File.Quit" operation invoked
        # by the viewer's UI. The trouble is that -- unless the user has
        # previously checked "never ask me again" -- this pops up "Are you
        # sure you want to quit?" From a script's point of view, this is Bad.
        # So instead we engage the lower-level "requestQuit" operation,
        # bypassing the prompt.
        self.send(pump="LLAppViewer", data=dict(op="requestQuit"))
        # loop until we see ViewerShutdown exception.
        try:
            # How long should it reasonably take for a healthy viewer to
            # respond to shutdown?
            end = time.time() + 60
            while time.time() < end:
                if not self.connected:
                    # Yay, just what we wanted!
                    self.log.debug("viewer shutdown confirmed.")
                    return
                # Wait a bit. It's unreasonable to check many times a second,
                # but we don't want to wait too many extra seconds once the
                # viewer actually does shut down.
                eventlet.sleep(1)
            # Hmm. At this point the viewer is still connected despite the
            # shutdown request. That doesn't seem right somehow.
            raise ViewerWontShutdown("viewer seems to be ignoring shutdown() request")
        except TimeoutError:
            raise ViewerWontShutdown("shutdown() request seems to have hung the viewer")

    def request(self, pump, data, timeout=None):
        """
        Send the specified request LLSD, expecting exactly one reply. Block
        the calling coroutine until we receive that reply. If the request
        times out, the calling coroutine receives a TimeoutError exception.

        Every request() (or generate()) LLSD block we send will get stamped
        with a distinct ["reqid"] value. The requested event API must echo the
        same ["reqid"] field in each reply associated with that request. This way
        we can correctly dispatch interleaved replies from different requests.

        If the desired event API doesn't support the ["reqid"] echo convention,
        you should use send() instead -- since request() or generate() would
        wait forever for a reply stamped with that ["reqid"] -- and intercept
        any replies using WaitFor.

        Unless the request data already contains a ["reply"] key, we insert
        reply=self.replypump to try to ensure that the expected reply will be
        returned over the socket.
        """
        # Invent a new, unique reqid. Arrange to handle incoming events
        # bearing that reqid. Stamp the outbound request with that reqid, and
        # send it.
        reqid = self._requestSetup(pump, data)
        # Wait for a reply to arrive bearing this reqid.
        self.log.debug("request() waiting for a response with reqid %s, timeout %s", reqid, timeout)
        try:
            return self.pending[reqid].wait(timeout)
        finally:
            # Kill off our temporary WaitForReqid object, even if we leave
            # via timeout exception.
            self.log.debug("request() cleaning up %s", self.pending[reqid])
            del self.pending[reqid]

    def next_reqid(self):
        return next(self.reqid)

    def _requestSetup(self, pump, data):
        # Invent a new, unique reqid.
        reqid = self.next_reqid()
        # Instantiate a new WaitForReqid object associated with this
        # ViewerClient. The priority is irrelevant because, unlike the WaitFor
        # base class, WaitForReqid does not self-register on our
        # self.waitfors list. Instead, capture the new WaitForReqid object in
        # self.pending so _dispatch() can find it.
        self.pending[reqid] = WaitForReqid(self, reqid)
        # Copy the dict so we're not modifying our caller's data.
        data = data.copy()
        # As promised, stuff the reqid into the outbound request.
        data["reqid"] = reqid
        try:
            # If there isn't already a reply key, set one.
            data.setdefault("reply", self.replypump())
        except AttributeError:
            # We also use this method before self.replypump is even set, so
            # don't crump that first time around.
            pass
        # Send the request as usual.
        self.send(pump, data)
        # Show the new reqid to our caller.
        return reqid

    def generate(self, pump, data, timeout=None, until=lambda event: False):
        """
        Send the specified request LLSD, expecting an arbitrary number of
        replies. Each one is returned on receipt; if they arrive faster than
        next() calls, they are queued. If you omit until=, this is an infinite
        generator, like itertools.count(); it's up to the caller to recognize
        when the last reply has been received, and stop requesting more.

        If you pass until=<callable accepting(event)>, each response event is
        passed to that callable (after the yield). When the callable returns
        True, the generator terminates in the usual way.

        See remarks in request()'s docstring about ["reqid"].
        """
        # Invent a new, unique reqid. Arrange to handle incoming events
        # bearing that reqid. Stamp the outbound request with that reqid, and
        # send it.
        reqid = self._requestSetup(pump, data)
        try:
            # Now return every distinct result that arrives bearing that reqid.
            while True:
                self.log.debug("generate() waiting for a response with reqid %s, timeout %s",
                      reqid, timeout)
                event = self.pending[reqid].wait(timeout)
                yield event
                if until(event):
                    self.log.debug("generate() has yielded until= event, done")
                    break
        finally:
            # If we ever break this loop, clean up.
            self.log.debug("generate() termination cleaning up %s", self.pending[reqid])
            del self.pending[reqid]

    def _receive(self):
        try:
            while True:
                event = self.get()
                self._dispatch(event)
        except Exception as e:
            # If we get any exception from the receive/dispatch code other
            # than what we explicitly raise -- e.g. MemoryError, which we've
            # seen but whose origin remains mysterious -- then print the
            # stack trace as well as forwarding the exception.
            if not isinstance(e, ProtocolError):
                self.log.exception(" sending exception ".center(72, '='))
            # This structure assumes that an exception from self.get() (e.g.
            # ProtocolError) is unrecoverable. That is, there's no point in
            # resuming the loop.
            # Close the connection; we have no further use for it.
            self.close()
            # Flag that we're done with the connection. That will prevent any
            # subsequent WaitFor.wait() call from blocking indefinitely.
            self.connected = False
            # Forward the exception to everyone listening either on
            # self.pending or self.waitfors.
            for waitfor in self.pending.values():
                self.log.debug("sending %s to %s", e.__class__.__name__, waitfor)
                waitfor._exception(e)
            for p, w in self.waitfors:
                waitfor = w()
                # Still can't count on any given waitfor being live.
                if waitfor is not None:
                    self.log.debug("sending %s to %s", e.__class__.__name__, waitfor)
                    waitfor._exception(e)

    def _dispatch(self, event):
        """Called for every event arriving on self.socket"""
        # Every incoming event should be a dict containing ["pump"], ["data"].
        try:
            event.pop
        except AttributeError:
            raise ProtocolError("Incoming packet not a dict: %s" % event)
        pump = event.pop("pump", None)
        data = event.pop("data", None)
        if event:
            self.log.debug("_dispatch() discarding extra outer info: %s", event)

        # First, if the incoming event has a ["reqid"] key, look it up based
        # on that.
        try:
            reqid = data.pop("reqid")
        except (KeyError, AttributeError, TypeError):
            # If this is an unsolicited message (ie: not requested via a call
            # to request()) there will be no reqid so we will receive an
            # exception. If the C++ viewer code returns a dictionary, we will
            # see KeyError. For a list we will see a TypeError because it's
            # not an int index. If neither, we could get AttributeError due to
            # lack of pop() method.

            # By convention, we expect dictionaries, but let's be robust so
            # that VITA won't crash should it see a list.

            # No ["reqid"] key: treat it as unsolicited.
            self.log.debug('_dispatch() found no ["reqid"] key')
            return self._unsolicited(pump, data)
        # Do we have a corresponding WaitForReqid object in self.pending?
        try:
            # Don't pop() it here: generate() needs the entry to remain.
            waitfor = self.pending[reqid]
        except KeyError:
            # We don't remember sending a request with any such reqid. Treat
            # it as an unsolicited event.
            self.log.debug("_dispatch() found no WaitForReqid with reqid %s", reqid)
            # stick reqid back in, in case any WaitFor cares
            data["reqid"] = reqid
            return self._unsolicited(pump, data)
        # Okay, we've found the right WaitForReqid object, let it process the
        # event.
        self.log.debug("_dispatch() sending event to %s", waitfor)
        waitfor._handle(pump, data)

    def _unsolicited(self, pump, data):
        """Called if an incoming event has no ["reqid"] key, or if we don't
        recognize that reqid value"""
        # Every time we walk self.waitfors, we want to eliminate any dead
        # weakrefs. Sigh, early exit from the _handle() loop suggests that our
        # life will be much simpler with a separate pass to cull dead weakrefs.
        self.waitfors = [(p, w) for p, w in self.waitfors if w() is not None]
        # Recall that we maintain self.waitfors in descending order of
        # specified priority. Walk them in that order.
        for p, w in self.waitfors:
            waitfor = w()
            # Still can't count on any given waitfor being live.
            if waitfor is not None:
                if waitfor._handle(pump, data):
                    # As promised, the first WaitFor object to claim this
                    # event gets it, so don't show it to any other WaitFor.
                    self.log.debug("event claimed by %s", waitfor)
                    break
        else:
            # We also promise that if no existing WaitFor object claims a given
            # event, we simply discard that event.
            self.log.debug("_unsolicited() discarding unclaimed event")

    def _registerWaitFor(self, waitfor, priority):
        """Called by WaitFor.enable()"""
        # Use weakref to store the WaitFor object, so that when there are no
        # longer any other outstanding references to that object, our registry
        # won't itself keep it alive.
        self.waitfors.append((-priority, weakref.ref(waitfor)))
        # As promised, keep self.waitfors sorted in descending order of
        # specified priority. That's why we store negative priority above.
        self.waitfors.sort()

    def _unregisterWaitFor(self, waitfor):
        """Called by WaitFor.disable()"""
        # Rebuild the waitfors list in the same order, eliminating any
        # weakrefs that have expired (w() is None) along with the one we're
        # trying to unregister (w() is waitfor).
        self.waitfors = [(p, w) for p, w in self.waitfors if w() not in (None, waitfor)]

# ****************************************************************************
#   WaitFor and friends
# ****************************************************************************
class WaitFor(object):
    """
    An unsolicited event is handled by the highest-priority WaitFor subclass
    object willing to accept it. If no such object is found, the unsolicited
    event is discarded.

    - First, instantiate a WaitFor subclass object to register its interest in
      some incoming event(s). WaitFor instances are self-registering; merely
      instantiating the object suffices.
    - Any coroutine may call a given WaitFor object's wait() method. This blocks
      the calling coroutine until a suitable event arrives.
    - WaitFor's constructor accepts a float priority. Every incoming event
      (other than those claimed by request() or generate()) is passed to each
      extant WaitFor.filter() method in descending priority order. The first
      such filter() to return nontrivial data claims that event.
    - At that point, the blocked wait() call on that WaitFor object returns the
      item returned by filter().
    - WaitFor contains a queue. Multiple arriving events claimed by that WaitFor
      object's filter() method are added to the queue. Naturally, until the
      queue is empty, calling wait() immediately returns the front entry.

    It's reasonable to instantiate a WaitFor subclass whose filter() method
    unconditionally returns the incoming event, and whose priority places it
    last in the list. This object will enqueue every unsolicited event left
    unclaimed by other WaitFor subclass objects.

    It's not strictly necessary to associate a WaitFor object with exactly one
    coroutine. You might have multiple "worker" coroutines drawing from the same
    WaitFor object, useful if the work being done per event might itself involve
    "blocking" operations. Or a given coroutine might sample a number of WaitFor
    objects in round-robin fashion... etc. etc. Nonetheless, it's
    straightforward to designate one coroutine for each WaitFor object.
    """
    def __init__(self, vclient, priority, name=None):
        """
        Pass:
        vclient  is the ViewerClient instance with which this WaitFor is associated.
        priority is a float priority. Each incoming event is tested against
                 WaitFor objects in descending priority order.
        name     is an optional string to identify this instance for debugging.
        """
        self.vclient  = vclient
        self.priority = priority
        self.name     = name or str(id(self))
        self.registered = False
        self.queue = ExcQueue()    # arbitrary max size
        self.enable()

    def __str__(self):
        return "%s(%s)" % (self.__class__.__name__, self.name)

    def __del__(self):
        # N.B. If we want __del__() to be meaningful, ViewerClient's registry
        # must store weakrefs to WaitFor objects rather than normal
        # references. Otherwise, merely being registered in the associated
        # ViewerClient will suffice to keep a WaitFor object alive, preventing
        # its __del__() method from automatically disabling it.
        self.disable()

    def __enter__(self):
        """
        In case we want a WaitFor subclass object with temporary scope,
        support Context Manager protocol to enable and disable it.
        """
        self.enable()
        return self

    def __exit__(self, type, value, traceback):
        # disable this WaitFor regardless of whether an exception was raised
        self.disable()
        # do not swallow any exception
        return False

    def enable(self):
        """
        Re-enable a disable()d WaitFor object. New WaitFor objects are
        enable()d by default.
        """
        if not self.registered:
            self.vclient._registerWaitFor(self, self.priority)
            self.registered = True

    def disable(self):
        """
        Disable an enable()d WaitFor object.
        """
        if self.registered:
            self.vclient._unregisterWaitFor(self)
            self.registered = False

    def wait(self, timeout=None):
        """
        Block the calling coroutine until a suitable unsolicited event (one
        for which filter() returns the event) arrives.
        """
        # Once the ViewerClient on which we're registered is no longer
        # connected, no further items will be placed in our queue. In that
        # case, instead of waiting forever (or even just to our timeout),
        # raise ViewerShutdown. But of course -- as long as there are still
        # remaining items in the queue, the state of our ViewerClient doesn't
        # matter because we can retrieve those items.
        if self.queue.empty() and not self.vclient.connected:
            # ViewerClient has disconnected and the queue has been drained.
            raise ViewerShutdown()
        # Here, either the viewer is still connected or there are remaining
        # items in our queue.
        # Use canonical eventlet.Timeout() idiom. Happily, the documented
        # meaning of passing seconds=None is that no timer is scheduled and no
        # timeout will occur.
        with eventlet.Timeout(timeout, TimeoutError):
            return self.queue.get()

    def iterate(self):
        """
        Loop over wait() calls.

        We should probably support a timeout for iterate(), but first we must
        decide: is that a per-wait() timeout, or overall? Decide that when we
        hit a use case.
        """
        while True:
            yield self.wait()

    def filter(self, pump, data):
        """
        Override this method to examine the incoming event in whatever way
        makes sense.

        Return False (or any equivalent) to ignore this event.

        To claim the event, return the item you want placed in the queue.
        Typically you'd write:
        return data
        or perhaps
        return dict(pump=pump, data=data)
        or some variation.
        """
        raise NotImplementedError("You must subclass WaitFor and override its filter() method")

    def _handle(self, pump, data):
        # Test this event with the subclass filter() method. If it doesn't
        # pass the filter, we're not interested in it.
        item = self.filter(pump, data)
        if not item:
            return False
        # Okay, filter() claims this event.
        self.process(item)
        return True

    def process(self, item):
        # This item passed filter(). Add it to our queue for anyone who is (or
        # will be) wait()ing.
        self.queue.put(item)

    def _exception(self, exc):
        """Forward exception to any listeners"""
        self.queue.put(exc)

class WaitForEventOnPump(WaitFor):
    """
    This WaitFor subclass watches for any event on any of the specified
    LLEventPumps. For convenience, passing a single string pump name is
    equivalent to passing a sequence containing only that name.
    Presumably we've directed lleventhost to "listen" on those pumps; we test
    for events wrapped the way lleventhost wraps them.
    """
    def __init__(self, vclient, priority, pumps):
        if isinstance(pumps, str):
            # If a single string pump name was passed (typical), make a
            # singleton tuple from it so we can treat uniformly the case of
            # multiple pump names.
            pumps = (pumps,)
        WaitFor.__init__(self, vclient, priority, pumps)

    def filter(self, pump, data):
        # self.name is the 'pumps' param from our constructor
        if pump not in self.name:
            return None
        return dict(pump=pump, data=data)

class WaitForStartup(WaitForEventOnPump):
    """
    Monitor events on the viewer's StartupState event pump, updating our
    parent ViewerClient's startup_state attribute as they go by. For some
    purposes, we want to know the startup_state as it exists right now, rather
    than wading through whatever state transitions have already gone by -- or
    waiting for the next one.
    """
    def process(self, item):
        # In addition to queueing filtered items, implicitly update
        # ViewerClient.startup_state
        if item["pump"] == "StartupState":
            data = item["data"]
            self.vclient.startup_state = \
                self.vclient.State(enum=data.get("enum"), str=data.get("str"))
        # now pass this item to base-class method
        super(WaitForStartup, self).process(item)

class Redirect(object):
    """
    Redirect is a mixin that posts filtered events to some other WaitFor
    subclass's queue.
    """
    def __init__(self, other):
        self.other = other

    def process(self, item):
        self.other.process(item)

class WaitForUnclaimedReqid(WaitFor):
    """
    WaitForReqid (below) is designed for use with ViewerClient.request(),
    using ViewerClient.pending rather than ViewerClient.waitfors. This class
    is for use when we are less confident that an event with the specified
    reqid will ever arrive. If it does, though, we want to capture it.
    """
    def __init__(self, vclient, priority, reqid):
        super(WaitForUnclaimedReqid, self).__init__(vclient, priority, str(reqid))
        self.reqid = reqid

    def filter(self, pump, data):
        if data.get("reqid") != self.reqid:
            return None
        return dict(pump=pump, data=data)

class RedirectUnclaimedReqid(Redirect, WaitForUnclaimedReqid):
    """
    If we receive an event with specified reqid, redirect it to this 'other'
    WaitFor subclass's queue.
    """
    def __init__(self, other, vclient, priority, reqid):
        Redirect.__init__(self, other)
        WaitForUnclaimedReqid.__init__(self, vclient, priority, reqid)

class WaitForReqid(WaitFor):
    """
    This WaitFor subclass is specialized for the ViewerClient.request() and
    generate() methods.
    """
    def __init__(self, vclient, reqid):
        # priority is meaningless, since this object won't be added to the
        # priority-sorted ViewerClient.waitfors list. Use the reqid as the
        # debugging name string.
        super(WaitForReqid, self).__init__(vclient, 0, str(reqid))

    def enable(self):
        # Do NOT self-register in the normal way. request() and generate()
        # have an entirely different registry that points directly to the
        # WaitForReqid object of interest.
        pass

    def disable(self):
        pass

    def filter(self, pump, data):
        # Because we expect to directly look up the WaitForReqid object of
        # interest based on the incoming ["reqid"] value, it's not necessary
        # to test the event again. Accept every such event.
        return data

# ****************************************************************************
#   ExcQueue: eventlet queue capable of propagating an exception
# ****************************************************************************
class ExcQueue(eventlet.queue.LightQueue):
    """
    When you put() an Exception subclass instance on this Queue subclass,
    the corresponding get() will raise that exception on the consumer
    coroutine.
    """
    def get(self, *args, **kwds):
        return self.check_exc(super(ExcQueue, self).get(*args, **kwds))

    def get_nowait(self, *args, **kwds):
        return self.check_exc(super(ExcQueue, self).get_nowait(*args, **kwds))

    def check_exc(self, item):
        if isinstance(item, Exception):
            raise item
        return item

    def iterate(self, *args, **kwds):
        """
        This is just too handy. Queue in general should have this method.
        """
        # An infinite loop like this can be tolerable in a coroutine. Note
        # that the producer can break a consumer's iterate() loop by putting a
        # StopIteration instance on the queue: the self.get() call will duly
        # raise that exception.
        while True:
            yield self.get(*args, **kwds)
