#!/usr/bin/env python


"""
@file   test_update_manager_make_VVM_UUID_hash.py
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

import update_manager
from vmp_util import Application

def test_make_VVM_UUID_hash():
    #because the method returns different results on different hosts
    #it is not easy to unit test it reliably.  
    #About the best we can do is check for the exception from subprocess
    key = Application.platform_key()

    UUID_hash = update_manager.make_VVM_UUID_hash(key)

    #make_UUID_hash returned None
    assert UUID_hash, "make_UUID_hash failed to make a hash."
