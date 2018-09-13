#!/usr/bin/python
"""\
@file   leap.py
@author Nat Goodspeed
@date   2012-03-14
@brief  Python implementation of LEAP (LLSD Event API Plugin) protocol

This module supports Python scripts used as viewer LEAP plugins. Every such
script must be able to send to stdout, and receive on stdin, LEAP protocol.

LEAP protocol passes serialized LLSD objects in both directions. A typical
LLSD object is a map containing keys 'pump' and 'data'.

Each LLSD object written to stdout is treated as a request to send an event.
The LLSD object that is the value of 'data' is posted to the LLEventPump named
by the value of 'pump'. This is typically used to engage an LLEventAPI method.

Similarly, each LEAP plugin gets its own LLEventPump with a unique name. Every
event received on that LLEventPump is serialized to the plugin's stdin,
wrapped in an outer map. The outer map's 'pump' key specifies the name of the
plugin's LLEventPump, the 'data' key stores the event LLSD.

On startup, an initial LLSD map is delivered to the plugin's stdin. This map's
'pump' key names the plugin's LLEventPump. The plugin can specify that pump
name as the 'reply' key in any LLEventAPI request that will produce a reply
event.

To deal with partial writes at either end, to make it completely unambiguous
when a complete LLSD object has been received, the protocol requires a length
prefix for every LLSD object:
length:serialized_LLSD

where:
'length' is a decimal integer stating the byte length of serialized_LLSD;
':' is literally a colon character;
'serialized_LLSD' is notation-format LLSD.

In addition to the above, each line written to stderr is logged to the
viewer's log -- but our consumer script needs no special support from us to
write to stderr.

$LicenseInfo:firstyear=2012&license=viewerlgpl$
Copyright (c) 2012, Linden Research, Inc.
$/LicenseInfo$
"""

import re
import os
import sys
from llbase import llsd
from eventlet import tpool

# It's important to wrap sys.stdin in a tpool.Proxy. We want to be able to
# block one eventlet coroutine waiting for data on stdin, WITHOUT blocking the
# whole process.
sys.stdin = tpool.Proxy(sys.stdin)

class ProtocolError(Exception):
    def __init__(self, msg, data):
        Exception.__init__(self, msg)
        self.data = data

class ParseError(ProtocolError):
    pass

def get(f=None):
    """Read LLSD from the passed open file-like object (default sys.stdin)"""
    if f is None:
        f = sys.stdin
    data = _get(f)
    try:
        return llsd.parse(data)
    except llsd.LLSDParseError, e:
        msg = 'Bad received packet (%s)' % e
        print >>sys.stderr, '%s, %s bytes:' % (msg, len(data))
        showmax = 40
        # We've observed failures with very large packets;
        # dumping the entire packet wastes time and space.
        # But if the error states a particular byte offset,
        # truncate to (near) that offset when dumping data.
        location = re.search(r' at (byte|index) ([0-9]+)', str(e))
        if not location:
            # didn't find offset, dump whole thing, no ellipsis
            ellipsis = ''
        else:
            # found offset within error message
            trunc = int(location.group(2)) + showmax
            data = data[:trunc]
            ellipsis = '... (%s more)' % (length - trunc)
        offset = -showmax
        for offset in xrange(0, len(data)-showmax, showmax):
            print >>sys.stderr, '%04d: %r +' % \
                  (offset, data[offset:offset+showmax])
        offset += showmax
        print >>sys.stderr, '%04d: %r%s' % \
              (offset, data[offset:], ellipsis)
        raise ParseError(msg, data)

def _get(f):
    """Read raw string data in length:data protocol form"""
    hdr = ''
    while ':' not in hdr and len(hdr) < 20:
        hdr += f.read(1)
        if not hdr:
            # Here if read(1) returned empty string, i.e. EOF
            sys.exit(0)
##         print >>sys.stderr, "_get(): hdr = %r" % hdr
    if not hdr.endswith(':'):
        raise ProtocolError('Expected len:data, got %r' % hdr, hdr)
    try:
        length = int(hdr[:-1])
    except ValueError:
        raise ProtocolError('Non-numeric len %r' % hdr[:-1], hdr[:-1])
##     print >>sys.stderr, "_get(): waiting for %s bytes" % length
    parts = []
    received = 0
    while received < length:
        parts.append(f.read(length - received))
        received += len(parts[-1])
##         print >>sys.stderr, "_get(): received %s of %s bytes: %s" % \
##               (received, length, ''.join(parts)[:50])
    data = ''.join(parts)
    assert len(data) == length
    return data

# deal with initial stdin message
# this will throw if the initial write to stdin doesn't
# follow len:data protocol, or if we couldn't find 'pump'
# in the dict
_initial  = get()
_reply    = _initial['pump']
_features = _initial['data']['features']
_command  = _initial['data']['command']

def replypump():
    return _reply

def cmdpump():
    return _command

def put(req, f=None):
    if f is None:
        f = sys.stdout
    f.write(':'.join((str(len(req)), req)))
    f.flush()

def send(pump, data, f=None):
    put(llsd.format_notation(dict(pump=pump, data=data)), f=f)

def request(pump, data, f=None):
    # we expect 'data' is a dict
    xdata = data.copy()
    xdata['reply'] = _reply
    send(pump, xdata, f=f)
