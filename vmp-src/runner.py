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
import subprocess
import sys

import InstallerUserMessage
from vmp_util import SL_Logging

class Runner(object):
    def __init__(self, *command):
        """
        Pass the command line to run, broken into the command and individual
        arguments as for subprocess.Popen.
        """
        self.command = command

    def run(self):
        raise NotImplementedError("Use a Runner subclass for %s" % (self.command,))

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

class PopenRunner(Runner):
    def run(self):
        """
        Launch the stored 'command' using subprocess.Popen().

        If the launch attempt fails, squawk in various ways (log, stderr, popup)
        and terminate.

        If it succeeds, return the subprocess.Popen object.
        """
        log=SL_Logging.getLogger('PopenRunner')
        log.info("Launching %s", (self.command,))

        env = os.environ.copy()
        env["PARENT"] = "SL_Launcher" # suppresses warning about not running the viewer directly

        with self.error_trap(log):
            viewer_process = subprocess.Popen(self.command, env=env)

        log.info("Successfully launched %s", (self.command,))
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
        if sys.platform.startswith('win') or sys.platform == 'cygwin':
            # MAINT-7831: Windows doesn't have a native execv(), and it's not
            # clear that Python's os.execv() emulation is working for us. Use
            # subprocess.Popen in this scenario too.
            log.info("Running %s", (self.command,))
            with self.error_trap(log):
                subprocess.Popen(self.command)

            # If we succeeded, terminate immediately so installer can replace
            # this running executable.
            sys.exit()

        else:                               # any platform other than Windows
            # In this case os.execv() should actually replace this process, just
            # as we want.
            log.info("Executing %s", (self.command,))

            # ensure that logs are closed and flushed before execing
            logging.shutdown()
            # We've just shut down logging; do NOT pass 'log'.
            with self.error_trap():
                os.execv(self.command[0], self.command)
                # if that worked, we're gone...

            # process has been replaced or killed - does not return
