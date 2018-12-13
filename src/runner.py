#!/usr/bin/python
"""\
@file   runner.py
@author Nat Goodspeed
@date   2017-10-17
@brief  Runner class and its specializations

$LicenseInfo:firstyear=2017&license=viewerlgpl$
Copyright (c) 2017, Linden Research, Inc.
$/LicenseInfo$
"""

from contextlib import contextmanager
import logging
import os
import platform
import subprocess
import sys

import InstallerUserMessage
from util import SL_Logging, Application, subprocess_args

class Runner(object):
    def __init__(self, *command, **kwds):
        """
        Pass the command line to run, broken into the command and individual
        arguments as for subprocess.Popen.

        On Windows, the keyword-only argument window=False (default True)
        hides the new child process's window.
        """
        self.command = command
        self.window  = kwds.pop("window", True)

    def run(self):
        raise NotImplementedError("Use a Runner subclass for %s" % (self.command,))

    def fix_show_window(self, kwds):
        # On Windows, util.subprocess_args() sets startupinfo to a
        # subprocess.STARTUPINFO object whose dwFlags and wShowWindow fields
        # are set to hide the new subprocess's window. If our consumer doesn't
        # want to show the child window, that's already taken care of.
        if not self.window:
            return kwds

        # When our consumer DOES want to show the child window, suppress the
        # startupinfo keyword argument set by subprocess_args(). Note that
        # setting startupinfo=None works on any platform.
        kwds = kwds.copy()
        kwds['startupinfo'] = None
        return kwds

    @contextmanager
    def error_trap(self, log=None):
        """
        Usage:

        # to log launch failure
        with self.error_trap(log):
            # ... attempt to launch self.command ...

        # If the launch attempt raises an exception, the 'with' block will not
        # return. If control reaches the next statement, the launch attempt
        # succeeded.

        # to avoid failure logging
        with self.error_trap():
            # ... attempt to launch self.command ...
        """
        try:
            yield
        except Exception as err:
            if log:
                log.error("Failed to launch %s. Error messages as follows:\n%r",
                          self.command[0], err)
                message = "Failed to launch %s, see log for details" % self.command[0]
            else:
                message = "Failed to launch %r\n%r" % (self.command, err)
            InstallerUserMessage.basic_message(message)
            sys.exit(-1)

    def Popen(self, command, **kwds):
        """
        This Popen() method is intended as a plug-compatible wrapper for
        subprocess.Popen().

        On Windows, with Python 2, passing a Unicode command pathname fails
        due to encoding issues. What works is to split() the pathname, change
        to the containing directory and then execute the filename.
        """
        if platform.system() != "Windows":
            return subprocess.Popen(command, **kwds)

        # On Windows, use MAINT-8087 workaround.
        # Get command as a list.
        if isinstance(command, basestring):
            command = [command]
        else:
            command = list(command)

        # DON'T pass subprocess the whole pathname, just the unqualified
        # program name. (We assume a command[0]. If you pass an empty list,
        # you get what you deserve.)
        progdir, prog = os.path.split(command[0])
        command[0] = prog

        # change to the program's directory
        olddir = os.getcwd()
        os.chdir(progdir)
        try:
            return subprocess.Popen(command, **kwds)
        finally:
            # try to restore previous directory
            try:
                os.chdir(olddir)
            except OSError:
                # restoring the previous directory is best effort (because in
                # the non-ASCII case, we might get an unusable path back from
                # getcwd()), but frankly we don't much care
                pass        

class PopenRunner(Runner):
    def run(self):
        """
        Launch the stored 'command' using subprocess.Popen().

        If the launch attempt fails, squawk in various ways (log, stderr, popup)
        and terminate.

        If it succeeds, return the subprocess.Popen object.
        """
        log=SL_Logging.getLogger('PopenRunner')
        log.info("Launching %s", self.command)

        with self.error_trap(log):
            # In the frozen environment constructed by PyInstaller on Windows,
            # unless we override both stdout and stderr, we get the dreaded
            # WindowsError(6, 'The handle is invalid') exception. However --
            # if we pass SL_Logging.stream(), as is customary for other
            # subprocess calls, the viewer takes that as invitation to
            # duplicate its voluminous log output into our SL_Launcher.log as
            # well as its own SecondLife.log.
            kwds = subprocess_args(log_stream=open(os.devnull, "w"))
            # Do NOT let subprocess_args() suppress the viewer window!
            kwds = self.fix_show_window(kwds)
            viewer_process = self.Popen(self.command, **kwds)

        log.info("Successfully launched %s", self.command)
        return viewer_process

class ExecRunner(Runner):
    def run(self):
        """
        Launch the stored 'command' as a replacement for the current process.
        Depending on the platform, the executable may be an installer or the next viewer.

        This method never returns: either the stored 'command' replaces this
        process, or we produce an error and die.
        """
        log=SL_Logging.getLogger('ExecRunner')
        if platform.system() == 'Windows':
            # MAINT-7831: Windows doesn't have a native execv(), and it's not
            # clear that Python's os.execv() emulation is working for us. Use
            # subprocess.Popen in this scenario too.
            log.info("Running %s", self.command)
            with self.error_trap(log):
                # see comment about log_stream in PopenRunner.run()
                kwds = subprocess_args(log_stream=open(os.devnull, "w"))
                kwds = self.fix_show_window(kwds)
                self.Popen(self.command, **kwds)

            # If we succeeded, terminate immediately so installer can replace
            # this running executable.
            sys.exit()

        else:                               # any platform other than Windows
            # In this case os.execv() should actually replace this process, just
            # as we want.
            log.info("Executing %s", self.command)

            # ensure that logs are closed and flushed before execing
            logging.shutdown()
            # We've just shut down logging; do NOT pass 'log'.
            with self.error_trap():
                os.execv(self.command[0], self.command)
                # if that worked, we're gone...

            # process has been replaced or killed - does not return
