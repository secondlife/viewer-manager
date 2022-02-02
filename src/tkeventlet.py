#!/usr/bin/python
"""\
@file   tkeventlet.py
@author Nat Goodspeed
@date   2018-02-16
@brief  This module integrates Tkinter with eventlet in such a way that
        we can call the Tkinter root window's mainloop() on one greenthread
        while continuing to let other greenthreads on the same (real Python)
        thread make progress.

$LicenseInfo:firstyear=2018&license=viewerlgpl$
Copyright (c) 2018, Linden Research, Inc.
$/LicenseInfo$
"""

import eventlet
from functools import partial
import tkinter as tk

class Error(Exception):
    pass

class TkGreenthread(object):
    """
    This class effects an integration between Tkinter and eventlet
    greenthreads. The basic idea is that you instantiate TkGreenthread in an
    eventlet greenthread, passing the root window (Tk subclass) and the
    polling interval. TkGreenthread arranges to be polled by Tkinter, then
    calls the root window's mainloop(). On every tick, it runs all ready
    eventlet greenthreads. The constructor returns if/when the user closes the
    root window.
    """
    def __init__(self, root=None, interval=0.5):
        """
        Pass:

        root: the Tkinter root window (Tk subclass) whose mainloop() to call.
              Pass None to leave no visible root window (for applications that
              only want to use Frames).

        interval:   Set this slider where the application needs it, balancing
                    CPU spin (0, polling constantly) against lag in eventlet
                    greenthread responsiveness.
        """
        self.interval = interval

        # application's root Tk window
        if root is None:
            # user elected not to pass a main window -- create a dummy one
            root = tk.Tk()
            # but don't display it
            root.withdraw()
        self.root = root

        # next Tk.after() timer handle
        self.next = None

        # Queue up the poll() sequence -- it will start once we call
        # self.root.mainloop()
        self.poll()
        # start handling Tkinter events, including the user closing self.root
        try:
            self.root.mainloop()
        finally:
            # mainloop() exits when user closes root window -- don't leave
            # timer dangling
            self.root.after_cancel(self.next)

    def poll(self):
        # run whoever else is ready before returning here
        eventlet.sleep(0)
        # queue this method again (timeout in milliseconds)
        # save timer handle for future cancellation
        self.next = self.root.after(int(self.interval * 1000), self.poll)
        # N.B. Why not use after_idle()? Because continuously rescheduling
        # after_idle() would hang the event loop:
        # https://mail.python.org/pipermail/tkinter-discuss/2010-May/002255.html
