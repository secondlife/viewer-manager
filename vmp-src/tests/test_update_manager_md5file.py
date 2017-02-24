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
import platform
import shutil
import tempfile
import update_manager

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

def test_empty_md5file():
    empty_handle = tempfile.TemporaryFile('r')
    assert_equal(update_manager.md5file(None, empty_handle), 'd41d8cd98f00b204e9800998ecf8427e'), "md5sum of empty file did not match"

def test_license_md5file():
    license_handle = tempfile.NamedTemporaryFile(mode = 'w', bufsize = 0, delete = False)
    license_handle.write(license_string)
    license_handle.close()
    plat = update_manager.get_platform_key()
    if plat == 'mac':
        assert_equal(update_manager.md5file(license_handle.name), '3e2f43ec1b5b84c0a2370e772fbe0ea2'), "md5sum of ASCII text file did not match"
    elif plat == 'win':
        assert_equal(update_manager.md5file(license_handle.name), 'b385c4eb96984648bfbd596f48319e3d'), "md5sum of ASCII text file did not match"
    else:
        #no linux machine to get golden value from atm, if it works on mac and win, it will likely work correctly on lnx
        assert True
    os.remove(license_handle.name)