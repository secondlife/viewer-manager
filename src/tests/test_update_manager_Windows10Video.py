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

from nose.tools import assert_equal, assert_false, assert_true

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
        with patch(update_manager, "wmic",
                   lambda *args:
                   # This string literal is actual observed wmic output on a Windows 7
                   # machine. No idea why it uses '\r\r\n' as end-of-line. <eyeroll/>
                   'Name                    \r\r\n'
                   'NVIDIA GeForce GTS 450  \r\r\n'
                   '\r\r\n'):
            assert_false(update_manager.WindowsVideo.isUnsupported())

    def testOneBadOneGood(self):
        with patch(update_manager, "wmic",
                       lambda *args:
                       'Name                    \r\r\n'
                       'Intel(R) HD Graphics    \r\r\n'
                       'NVIDIA GeForce GTS 450  \r\r\n'
                       '\r\r\n'):
            assert_false(update_manager.WindowsVideo.isUnsupported())

    def testTwoBad(self):
        with patch(update_manager, "wmic", 
                       lambda *args: 
                       'Name                    \r\r\n' 
                       'Intel(R) HD Graphics 3000 \r\r\n' 
                       'Intel(R) HD Graphics 4000 \r\r\n'
                       '\r\r\n'): 
            assert_equal(update_manager.WindowsVideo.isUnsupported(), True)

    def testNoCards(self):
        with patch(update_manager, "wmic", 
                       lambda *args: 
                       'Name                    \r\r\n' 
                       '\r\r\n'): 
            assert_true(update_manager.WindowsVideo.isUnsupported())

    def testBadWmic(self):
        def wmic(*args):
            raise update_manager.WmicError("fake error")
        with patch(update_manager, "wmic", wmic):
            assert_true(update_manager.WindowsVideo.isUnsupported())
