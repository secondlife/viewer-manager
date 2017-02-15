#!/usr/bin/env python


"""
@file   test_sl_launcher_silent_write.py
@author coyot
@date   2016-06-02

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

import imp
import os.path
import tempfile

#shenanigans around importing a file that doesn't end in .py
#the scripts are in the parent directory of the tests, hence the double dirname call
launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'SL_Launcher')
#if you import it normally, it tries to run main() at import time
SLL = imp.load_source('SL_Launcher',launcher)

def test_silent_write_to_file(): 
    test_log = tempfile.TemporaryFile()
    try:
        SLL.silent_write(test_log, "This is a test.")
    except Exception, e:
        print "Test failed due to: %s" % str(e)
        assert False

def test_silent_write_to_null(): 
    try:
        SLL.silent_write(None, "This is a test.")
    except Exception, e:
        print "Test failed due to: %s" % str(e)
        assert False
