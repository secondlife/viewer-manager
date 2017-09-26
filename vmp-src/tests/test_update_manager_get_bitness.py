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


from nose.tools import assert_equal

import os
import update_manager
from patch import patch, patch_dict, DELETE

def test_linux():
    bitness = update_manager.getBitness('lnx')
    assert_equal(bitness, 64)

def test_mac():
    bitness = update_manager.getBitness('mac')
    assert_equal(bitness, 64)

def test_win32():
    with patch_dict(os.environ, 'PROGRAMFILES(X86)', 'present'):
        assert_equal(update_manager.getBitness('win'), 64)
    with patch_dict(os.environ, 'PROGRAMFILES(X86)', DELETE):
        assert_equal(update_manager.getBitness('win'), 32)


