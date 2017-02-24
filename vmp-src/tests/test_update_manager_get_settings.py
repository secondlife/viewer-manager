#!/usr/bin/env python


"""
@file   test_update_manager_get_settings.py
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

import os
import shutil
import tempfile
import update_manager
import with_setup_args

data_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data')

def get_settings_setup():
    tmpdir1 = tempfile.mkdtemp()
    log_file_path = os.path.abspath(os.path.join(tmpdir1,"update_manager.log"))
    log_file_handle = open(log_file_path, 'w', 0)
    return [tmpdir1, log_file_path, log_file_handle], {}

def get_settings_teardown(tmpdir1, log_file_path, log_file_handle):
    shutil.rmtree(tmpdir1, ignore_errors = True)

@with_setup_args.with_setup_args(get_settings_setup, get_settings_teardown)
def test_get_settings(tmpdir1, log_file_path, log_file_handle):   
    settings_llsd = update_manager.get_settings(log_file_handle, data_dir)
    #we aren't testing the LLSD library, one dictionary value is enough
    assert_equal(settings_llsd['CurrentGrid']['Value'],'util.agni.lindenlab.com')

@with_setup_args.with_setup_args(get_settings_setup, get_settings_teardown)
def test_get_settings_bad_key(tmpdir1, log_file_path, log_file_handle):
    settings_llsd = update_manager.get_settings(log_file_handle, data_dir)
    try:
        settings_llsd['LagAmount']['Value']
    except KeyError:
        assert True
    except Exception, e:
        print "Non KeyError from bad key test: %s" % repr(e)
        assert False
        
@with_setup_args.with_setup_args(get_settings_setup, get_settings_teardown)
def test_get_settings_bad_path(tmpdir1, log_file_path, log_file_handle):
    flag = False
    try:
        settings_llsd = update_manager.get_settings(log_file_handle, os.path.dirname(data_dir))
    except Exception, e:
        #should not happen, get_settings should consume the exception and log it
        print "get settings not quiet, threw %s" % e
        assert flag
        return
    #None is the signal retcode for failure
    if settings_llsd is None:
        flag = True
    assert flag