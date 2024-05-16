#!/usr/bin/env python


"""
@file   test_update_manager_check_for_completed_download.py
@author coyot
@date   2016-06-03

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

from nose_tools import *

import os
import shutil
import tempfile
import update_manager

def setup_function():
    global tmpdir1, tmpdir2
    tmpdir1 = tempfile.mkdtemp(prefix = 'test1')
    tmpdir2 = tempfile.mkdtemp(prefix = 'test2')
    tempfile.mkstemp(suffix = '.done', dir = tmpdir1)

def teardown_function():
    shutil.rmtree(tmpdir1, ignore_errors = True)
    shutil.rmtree(tmpdir2, ignore_errors = True)

def test_completed_check_for_completed_download():
    assert_equal(update_manager.check_for_completed_download(tmpdir1), 'done'), "Failed to find completion marker"

def test_incomplete_check_for_completed_download():
    #should return False
    incomplete = not update_manager.check_for_completed_download(tmpdir2)
    assert incomplete, "False positive, should not mark complete without a marker"
