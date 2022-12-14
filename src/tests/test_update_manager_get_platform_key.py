#!/usr/bin/env python

"""
@file   test_update_manager_get_platform_key.py
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

from nose_tools import assert_equal

import platform
from util import Application

def test_get_platform_key():
    key = Application.platform_key()
    if key == 'mac':
        assert_equal(platform.system(),'Darwin')
    elif key == 'lnx':
        assert_equal(platform.system(),'Linux')
    elif key == 'win':
        assert_equal(platform.system(),'Windows')
    else:
        assert_equal(key, None)
