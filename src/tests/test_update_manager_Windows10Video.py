#!/usr/bin/env python

"""\
@file   test_update_manager_Windows10Video.py
@author oz
@date   2017-09-25

$LicenseInfo:firstyear=2016&license=viewerlgpl$
Second Life Viewer Source Code
Copyright (C) 2016, Linden Research, Inc.

This library is free software; you can redistribute it and/or
modify it under the terms of the GNU Lesser General Public
License as published by the Free Software Foundation;
version 2.1 of the License only.

This library is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public
License along with this library; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

Linden Research, Inc., 945 Battery Street, San Francisco, CA  94111  USA
$/LicenseInfo$
"""

from nose_tools import assert_equal, assert_false, assert_true

import os
import sys
import platform

from patch import patch, patch_dict, DELETE

# when running individual test files, this is needed for the imports below
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_manager

class testWindowsVideo(object):

    def setup(self):
        update_manager.WindowsVideo.hasOnlyUnsupported = None # defeat caching so each test rechecks
        os.environ['APP_DATA_DIR'] = os.path.dirname(os.path.abspath(__file__))

    def testOnlyOneGoodCard(self):
        with patch(update_manager, "pshell",
                   lambda *args:
                   'NVIDIA GeForce GTS 450  \r\r\n'
                   '\r\r\n'):
            assert_false(update_manager.WindowsVideo.isUnsupported())

    def testOneBadOneGood(self):
        with patch(update_manager, "pshell",
                       lambda *args:
                       'Intel(R) HD Graphics 2000 \r\r\n'
                       'NVIDIA GeForce GTS 450    \r\r\n'
                       '\r\r\n'):
            assert_false(update_manager.WindowsVideo.isUnsupported())

    def testTwoBad(self):
        with patch(update_manager, "pshell", 
                       lambda *args:
                       'Intel(R) HD Graphics 2000 \r\r\n' 
                       'Intel(R) HD Graphics 3000 \r\r\n'
                       '\r\r\n'): 
            assert_equal(update_manager.WindowsVideo.isUnsupported(), True)

    def testNoCards(self):
        with patch(update_manager, "pshell", 
                       lambda *args: 
                       '\r\r\n'): 
            assert_true(update_manager.WindowsVideo.isUnsupported())

    def testBadPShell(self):
        def pshell(*args):
            raise update_manager.PShellError("fake error")
        with patch(update_manager, "pshell", pshell):
            assert_true(update_manager.WindowsVideo.isUnsupported())

    def testBadIntelHDGraphics(self):
        def pshell(*args):
            if args[0] == 'path':
                return 'Intel(R) HD Graphics      \r\r\n'\
                       '\r\r\n'
            else:
                return 'Intel(R) Core(TM) i7-2600 CPU @ 3.20GHz \r\r\n'\
                       '\r\r\n'
        with patch(update_manager, "pshell", pshell):
            assert_true(update_manager.WindowsVideo.isUnsupported())

    def testGoodIntelHDGraphics(self):
        def pshell(*args):
            if args[0] == 'path':
                return 'Intel(R) HD Graphics      \r\r\n'\
                       '\r\r\n'
            else:
                return 'Intel(R) Core(TM) i5-6600K CPU @ 3.20GHz \r\r\n'\
                       '\r\r\n'
        with patch(update_manager, "pshell", pshell):
            assert_false(update_manager.WindowsVideo.isUnsupported())
