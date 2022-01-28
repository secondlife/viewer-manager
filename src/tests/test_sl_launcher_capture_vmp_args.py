#!/usr/bin/env python


"""
@file   test_sl_launcher_capture_vmp_args.py
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

from nose_tools import *

from get_cmd_line import get_cmd_line
import os
import os.path
import platform
import shutil
import with_setup_args
from util import BuildData
import SLVersionChecker as SLL

#the {Resources}/app_settings dir is a sibling of the parent of the script dir
source_dir = os.path.join(os.path.dirname(SLL.__file__), os.pardir)
golden_cmd_xml = os.path.join(source_dir, 'src', 'tests', 'data', 'cmd_line.xml')
plat = platform.system()
path_dict = {'Darwin':os.path.join(source_dir, 'Resources', 'app_settings', 'cmd_line.xml'),
               'Linux':os.path.join(source_dir, 'app_settings', 'cmd_line.xml'),
               'Windows':os.path.join(source_dir, 'app_settings', 'cmd_line.xml')}
test_dir = os.path.dirname(path_dict[plat])
test_file = os.path.join(test_dir, 'cmd_line.xml')

def capture_vmp_args_setup():
    #makedirs errors if there are borked leftovers from a previous test, so wipe the plate clean
    shutil.rmtree(test_dir, ignore_errors = True)
    os.makedirs(test_dir)
    shutil.copyfile(golden_cmd_xml, path_dict[plat])
    BuildData.read(os.path.join(os.path.dirname(__file__),'build_data.json'))
    return [], {}

def capture_vmp_args_teardown():
    shutil.rmtree(test_dir, ignore_errors = True)

@with_setup_args.with_setup_args(capture_vmp_args_setup, capture_vmp_args_teardown)
def test_capture_vmp_args_empty():
    cmd_settings_file = get_cmd_line(test_file)
    overrides = SLL.capture_vmp_args(None, cmd_settings_file)
    #choose one key to test, we don't need to recapitulate LLSD parsing unit tests here
    assert_equal(overrides.get('channel'), None)

@with_setup_args.with_setup_args(capture_vmp_args_setup, capture_vmp_args_teardown)
def test_capture_vmp_args_simple():
    cmd_settings_file = get_cmd_line(test_file) 
    overrides = SLL.capture_vmp_args(['--channel', 'Bat'], cmd_settings_file)
    #choose one key to test, we don't need to recapitulate LLSD parsing unit tests here
    assert_equal(overrides['channel'], 'Bat')

@with_setup_args.with_setup_args(capture_vmp_args_setup, capture_vmp_args_teardown)
def test_capture_vmp_args_setter(): 
    cmd_settings_file = get_cmd_line(test_file)
    overrides = SLL.capture_vmp_args(['--set', 'UpdaterServiceSetting', '2'], cmd_settings_file)
    #choose one key to test, we don't need to recapitulate LLSD parsing unit tests here
    assert_equal(overrides['set']['UpdaterServiceSetting'], '2')
