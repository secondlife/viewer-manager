#!/usr/bin/env python


"""
@file   test_sl_launcher_get_cmd_line.py
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
import os
import os.path
import platform
import shutil
from vmp_util import BuildData
import with_setup_args

#shenanigans around importing a file that doesn't end in .py
#the scripts are in the parent directory of the tests, hence the double dirname call
launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'SL_Launcher')
#if you import it normally, it tries to run main() at import time
SLL = imp.load_source('SL_Launcher',launcher)

#the {Resources}/app_settings dir is a sibling of the parent of the script dir
source_dir = os.path.dirname(os.path.dirname(launcher))
golden_cmd_xml = os.path.join(source_dir, 'src/tests/data/cmd_line.xml')
plat = platform.system()
path_dict = {'Darwin':os.path.join(source_dir, 'Resources/app_settings/cmd_line.xml'),
               'Linux':os.path.join(source_dir, 'app_settings/cmd_line.xml'),
               'Windows':os.path.join(source_dir, 'app_settings/cmd_line.xml')}
test_dir = os.path.dirname(path_dict[plat])
test_file = os.path.join(test_dir, 'cmd_line.xml')

def get_cmd_line_setup():
    #makedirs errors if there are borked leftovers from a previous test, so wipe the plate clean
    BuildData.read(os.path.join(os.path.dirname(__file__),'build_data.json'))
    shutil.rmtree(test_dir, ignore_errors = True)
    os.makedirs(test_dir)
    shutil.copyfile(golden_cmd_xml, path_dict[plat])
    return [], {}

def get_cmd_line_teardown():
    shutil.rmtree(test_dir, ignore_errors = True)

#here we use a private to the repo copy the cmd line file so that the test is platform independent
#in particular, on Windows, sys.executable is different for nose (python) than the compiled exe
#which throws off various mechanisms that look for things relative to where they are.
@with_setup_args.with_setup_args(get_cmd_line_setup, get_cmd_line_teardown)
def test_get_cmd_line(): 
    result = SLL.get_cmd_line(test_file)
    #choose one key to test, we don't need to recapitulate LLSD parsing unit tests here
    assert_equal(result['set']['count'], 2)
