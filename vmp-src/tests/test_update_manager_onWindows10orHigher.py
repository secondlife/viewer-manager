#!/usr/bin/env python

"""\
@file   test_update_manager_chose_result.py
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

from nose.tools import assert_equal

import os
import sys
import platform

from patch import patch, patch_dict, DELETE

# when running individual test files, this is needed for the imports below
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_manager

def windows8version():
    """for patching platform.win32_ver"""
    return ("Windows 8", "8.3.4", "1", "Free")

def windows10version():
    """for patching platform.win32_ver"""
    return ("Windows 10", "10.1.5", "1", "Free")

def onWindows():
    """for patching platform.system"""
    return "Windows"

def onOther():
    """for patching platform.system"""
    return "Other"

class testOnWindows10orHigher(object):

    def setup(self):
        os.environ['APP_DATA_DIR'] = os.path.dirname(os.path.abspath(__file__))

    def test_onWindows8(self):
        with patch(platform, "system", onWindows), \
             patch(platform, "win32_ver", windows8version):
            assert_equal(update_manager.onWindows10orHigher(), False)

    def test_onWindows10(self):
        with patch(platform, "system", onWindows), \
             patch(platform, "win32_ver", windows10version):
            assert_equal(update_manager.onWindows10orHigher(), True)

    def test_onOther(self):
        with patch(platform, "system", onOther):
            assert_equal(update_manager.onWindows10orHigher(), False)

