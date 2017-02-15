#!/usr/bin/env python


"""
@file   test_update_manager_md5file.py
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

from nose.tools import *
from nose import with_setup

import os
import shutil
import tempfile
import update_manager
import with_setup_args

license_string = """
@file   test_update_manager_md5file.py
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

def md5file_setup():
    empty_fd, empty_name = tempfile.mkstemp()
    empty_handle = open(empty_name, mode='r')
    license_fd, license_name = tempfile.mkstemp()
    #unbuffered or it will look like an empty file by the time we get to the test
    license_handle = open(license_name, 'w', 0)
    license_handle.write(license_string)
    return [empty_handle, empty_name, license_handle, license_name], {}

def md5file_teardown(empty_handle, empty_name, license_handle, license_name):
    empty_handle.close()
    license_handle.close()
    os.remove(empty_name)
    os.remove(license_name)

@with_setup_args.with_setup_args(md5file_setup, md5file_teardown)
def test_empty_md5file(empty_handle, empty_name, license_handle, license_name):
    assert_equal(update_manager.md5file(empty_name), 'd41d8cd98f00b204e9800998ecf8427e'), "md5sum of empty file did not match"

@with_setup_args.with_setup_args(md5file_setup, md5file_teardown)
def test_incomplete_md5file(empty_handle, empty_name, license_handle, license_name):
    assert_equal(update_manager.md5file(license_name), '3e2f43ec1b5b84c0a2370e772fbe0ea2'), "md5sum of ASCII text file did not match"
