#!/usr/bin/env python
"""\
@file   test_update_manager_sleep_between.py
@author Nat Goodspeed
@date   2017-08-18
@brief  Test the update_manager.sleep_between() function

$LicenseInfo:firstyear=2017&license=viewerlgpl$
Copyright (c) 2017, Linden Research, Inc.
$/LicenseInfo$
"""

from nose_tools import *
import update_manager
from patch import patch

class DummySL_Logging(object):
    """
    Provide a getLogger() method that returns an instance of DummyLogger.
    """
    def __init__(self, captures):
        self.logger = DummyLogger(captures)

    def getLogger(self, name):
        return self.logger

class DummyLogger(object):
    """
    Behave like a logger, but capture log messages instead of printing them.
    """
    def __init__(self, captures):
        self.captures = captures

    def info(self, message):
        self.captures.append(message)

    # also behave like sleep(n) function
    def __call__(self, duration):
        self.info("{%s}" % duration)

def test_sleep_between():
    captures = []
    logging = DummySL_Logging(captures)
    with patch(update_manager, 'SL_Logging', logging), \
         patch(update_manager, 'sleep', logging.getLogger(None)):

        # no iterations
        for item in update_manager.sleep_between("", "m", 5):
            captures.append(item)
        # should be NO log lines and NO sleep() calls
        assert_equals(''.join(captures), "")

        # one iteration
        # To reset 'captures', it's important to delete all entries from the
        # EXISTING list rather than resetting 'captures' to a brand-new empty
        # list, since our DummyLogger instance (also masquerading as
        # update_manager.sleep()) is pointing to the original list.
        del captures[:]
        for item in update_manager.sleep_between("a", "m", 5):
            captures.append(item)
        # should be NO log lines and NO sleep() calls
        assert_equals(''.join(captures), "a")

        # two iterations
        del captures[:]
        for item in update_manager.sleep_between("ab", "m", 5):
            # The point of appending each of our items to the same captures
            # list is that we're trying to verify the sequence in which the
            # loop body is executed relative to the log and sleep calls.
            captures.append(item)
        # should be exactly one log line and one sleep call, in that order
        assert_equals(''.join(captures), "am{5}b")

        # three iterations
        del captures[:]
        for item in update_manager.sleep_between("abc", "m", 5):
            captures.append(item)
        # should be a log line and a sleep call between each iteration
        assert_equals(''.join(captures), "am{5}bm{5}c")

        # test {n}
        del captures[:]
        for item in update_manager.sleep_between("abc", "({n})", 5):
            captures.append(item)
        # {n} should expand differently on each iteration
        assert_equals(''.join(captures), "a(1){5}b(2){5}c")

        # test {t}
        del captures[:]
        for item in update_manager.sleep_between("abc", "({t})", 5):
            captures.append(item)
        # {t} simply reports the sleep duration on each iteration
        assert_equals(''.join(captures), "a(5){5}b(5){5}c")
