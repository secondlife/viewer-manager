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

from nose.tools import *
from nose import with_setup

import os
import os.path
import platform
import apply_update
import subprocess
import with_setup_args

plat = platform.system()

def try_dismount_setup():
    if plat is not 'Darwin':
        return [], {}
    script_dir = os.path.dirname(os.path.realpath(__file__))
    test_dmg = os.path.join(script_dir, 'tests/data/Second Life Installer.dmg')
    try:
        subprocess.check_output(["hdiutil", "attach", test_dmg, "-mountroot", tmpdir])
    except Exception, e:
        print "Test failed due to: %s" % str(e)
        assert False
    return [], {}

def try_dismount_teardown():
    pass

@with_setup_args.with_setup_args(try_dismount_setup, try_dismount_teardown)
def test_try_dismount():
    #we only dismount dmg files on Macs
    if plat is not 'Darwin':
        assert True
    else:
        try:
            apply_update.try_dismount(None, "SL TESTING", "/Volumes")
        except Exception, e:
            print "Test failed due to: %s" % str(e)
            assert False    

def test_try_dismount_missing_dmg():
    #this test runs after the previous one with no setup, so the dmg should alredy be unmounted
    #the idea is to test what happens when it tries to unmount something that isn't mounted.
    if plat is not 'Darwin':
        assert True  
    else:  
        try:
            apply_update.try_dismount(None, "Should Fail Silently", "/Volumes")
        except Exception, e:
            print "Test failed due to: %s" % str(e)
            assert False
