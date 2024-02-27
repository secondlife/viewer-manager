#!/usr/bin/env python


"""
@file   test_apply_update_try_dismount.py
@author coyot
@date   2016-06-30

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
import os.path
import platform

# ensure we find local build_data.json file
os.environ["APP_DATA_DIR"] = os.path.dirname(__file__)

import apply_update
import subprocess

plat = platform.system()

def setup_function(function):
    if plat != 'Darwin':
        return
    # test_try_dismount_missing_dmg() is supposed to run WITHOUT setup
    if function == test_try_dismount_missing_dmg:
        return
    script_dir = os.path.dirname(os.path.realpath(__file__))
    test_dmg = os.path.join(script_dir, 'data/Second Life Installer.dmg')
    subprocess.check_output(["hdiutil", "attach", test_dmg, "-mountroot", '/Volumes'],
                            universal_newlines=True)

def test_try_dismount():
    #we only dismount dmg files on Macs
    if plat == 'Darwin':
        apply_update.try_dismount("SL TESTING", "/Volumes")

def test_try_dismount_missing_dmg():
    #this test runs after the previous one with no setup, so the dmg should alredy be unmounted
    #the idea is to test what happens when it tries to unmount something that isn't mounted.
    if plat == 'Darwin':
        apply_update.try_dismount("Should Fail Silently", "/Volumes")
