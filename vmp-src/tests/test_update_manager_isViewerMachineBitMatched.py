#!/usr/bin/env python

"""\
@file   test_update_manager_convert_version_file_style.py
@author coyot
@date   2016-06-01

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


from nose.tools import *

import os
import update_manager

def test_no_viewer_platform():
    assert_equal(False, update_manager.isViewerMachineBitMatched(None, 'lnx', 64))
    
def test_no_platform_key():
    assert_equal(False, update_manager.isViewerMachineBitMatched('lnx', None, 64))
    
def test_linux_matched():
    assert_equal(True, update_manager.isViewerMachineBitMatched('lnx', 'lnx', 64))

def test_linux_mismatched():
    assert_equal(False, update_manager.isViewerMachineBitMatched('lnx', 'mac', 64))    

def test_mac_matched():
    assert_equal(True, update_manager.isViewerMachineBitMatched('mac', 'mac', 64))

def test_mac_mismatched():
    assert_equal(False, update_manager.isViewerMachineBitMatched('mac', 'lnx', 64))  
    
def test_win_matched32():
    assert_equal(True, update_manager.isViewerMachineBitMatched('win32', 'win', 32))

def test_win_matched64():
    assert_equal(True, update_manager.isViewerMachineBitMatched('win', 'win', 64))
    
def test_win_mismatched_OS_Viewer():
    assert_equal(False, update_manager.isViewerMachineBitMatched('mac', 'win', 64))

def test_win_mismatched_OS_Key():
    assert_equal(False, update_manager.isViewerMachineBitMatched('win', 'mac', 64))

def test_win_mismatched_32_64():
    assert_equal(False, update_manager.isViewerMachineBitMatched('win32', 'mac', 64))

def test_win_mismatched_64_32():
    assert_equal(False, update_manager.isViewerMachineBitMatched('win', 'mac', 32))
