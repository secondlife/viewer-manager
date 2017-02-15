#!/usr/bin/env python


"""
@file   test_download_update_download_update.py
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

import download_update
import fnmatch
import os
import os.path
import platform
import shutil
import tempfile
import update_manager
import with_setup_args

#Nota Bene: testing Tkinter UI elements should be done by a QA engineer as we don't have test infrastructure
#for graphical elements

parent_dir = update_manager.get_parent_path(update_manager.get_platform_key())
#doesn't really matter which viewer, the downloader just needs a file of sufficient length to test the chunking
#we allegedly never purge S3, so this should always be there
URL = "http://automated-builds-secondlife-com.s3.amazonaws.com/hg/repo/viewer-lynx/rev/323027/arch/Darwin/installer/Second_Life_5_0_1_323027_i386.dmg"
marker_regex = '*' + '.done'

def download_update_setup():
    tmpdir1 = tempfile.mkdtemp(prefix = 'test1')
    return [tmpdir1], {}

def download_update_teardown(tmpdir1):
    shutil.rmtree(tmpdir1, ignore_errors = True)

@with_setup_args.with_setup_args(download_update_setup, download_update_teardown)
def test_download_update_null_url(tmpdir1): 
    try:
        download_update.download_update(None, tmpdir1, None, False, 1024)
    #this is the expected error when d_u tries to apply split() to None
    except AttributeError, e:
        assert True
    #something else bad happened
    except Exception, e:
        print "download_update threw an exception on null URL: %s" % repr(e)
        assert False
    #we failed to fail
    else:
        assert False
        
@with_setup_args.with_setup_args(download_update_setup, download_update_teardown)
def test_download_update_correct_url(tmpdir1):
    try:
        download_update.download_update(URL, tmpdir1, None, False, 1024)
    except Exception, e:
        print "download_update threw an exception on a correct URL: %s" % repr(e)
        assert False
    else:
        #if behaving correctly, the downloader should leave a tmpfile with the
        #.done extension in the download directory (tmpdir1)
        flag = False
        for filename in os.listdir(tmpdir1):
            if fnmatch.fnmatch(filename, marker_regex):
                flag = True
        assert flag


