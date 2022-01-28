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
import logging
from util import SL_Logging, Application, BuildData

data_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data')
BuildData.read(os.path.join(os.path.dirname(__file__),'build_data.json'))
log=SL_Logging.getLogger('test_settings', verbosity='DEBUG')

def get_settings_setup():
    tmpdir1 = tempfile.mkdtemp()
    return [tmpdir1], {}

def get_settings_teardown(tmpdir1):
    shutil.rmtree(tmpdir1, ignore_errors = True)

@with_setup_args.with_setup_args(get_settings_setup, get_settings_teardown)
def test_get_settings(tmpdir1):   
    settings_llsd = update_manager.get_settings(
        os.path.join(data_dir, "user_settings", "settings.xml"))
    #we aren't testing the LLSD library, one dictionary value is enough
    assert_equal(settings_llsd['CurrentGrid'],'util.agni.lindenlab.com')

@with_setup_args.with_setup_args(get_settings_setup, get_settings_teardown)
def test_get_settings_bad_key(tmpdir1):
    settings_llsd = update_manager.get_settings(
        os.path.join(data_dir, "user_settings", "settings.xml"))
    try:
        settings_llsd['LagAmount']['Value']
    except KeyError:
        pass

@with_setup_args.with_setup_args(get_settings_setup, get_settings_teardown)
def test_get_settings_bad_path(tmpdir1):
    settings_llsd = update_manager.get_settings(os.path.dirname(data_dir))
    assert not settings_llsd
