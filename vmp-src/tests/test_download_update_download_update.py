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

import glob
import os
import os.path
import platform
import re
import shutil
import sys
import tempfile
import logging
from vmp_util import SL_Logging, Application, BuildData
from argparse import Namespace
import with_setup_args

#cygwin artifact: the installed llbase is in a cygwin directory but we
#use system python and it doesn't know from cygpaths, so the import misses
#and we get the system llbase instead.
windows = re.compile('win')
if windows.search(sys.platform.lower()):                     
    local_llbase = os.path.join(os.path.dirname(os.path.abspath(os.getcwd())), 
        'stage', 'packages', 'lib', 'python')
    os.environ['PYTHONPATH'] = local_llbase
    sys.path.insert(0, local_llbase)
os.environ['APP_DATA_DIR'] = os.path.dirname(__file__)
from llbase import llsd, llrest
import download_update

#Nota Bene: testing Tkinter UI elements should be done by a QA engineer as we don't have test infrastructure
#for graphical elements

# doesn't really matter which viewer, the downloader just needs a file of sufficient length to test the chunking
# we allegedly never purge S3, so this should always be there
URL = "http://automated-builds-secondlife-com.s3.amazonaws.com/hg/repo/viewer-lynx/rev/323027/arch/Darwin/installer/Second_Life_5_0_1_323027_i386.dmg"
URL_len = 92657704
marker_regex = '*' + '.done'

def download_update_setup():
    global log
    BuildData.read(os.path.join(os.path.dirname(__file__),'build_data.json'))
    # must override BuildData above before initializing log
    log=SL_Logging.getLogger('test_download', verbosity='DEBUG')
    # DO NOT try to download via a proxy!
    os.environ.pop("http_proxy", None)
    tmpdir1 = tempfile.mkdtemp(prefix = 'test1')   
    return [tmpdir1], {}

def download_update_teardown(tmpdir1):
    shutil.rmtree(tmpdir1, ignore_errors = True)

@with_setup_args.with_setup_args(download_update_setup, download_update_teardown)
def test_download_update_null_url(tmpdir1):     
    try:
        download_update.download_update(url=None, download_dir=tmpdir1, size=None, progressbar=False)
    #this is the expected error when d_u tries to apply split() to None
    except AttributeError, e:
        pass
    #something else bad happened
    except Exception, e:
        # preserve the original exception and its traceback
        raise
    #we failed to fail
    else:
        raise AssertionError("download_update() failed to raise exception for url=None")
        
@with_setup_args.with_setup_args(download_update_setup, download_update_teardown)
def test_download_update_correct_url(tmpdir1):
    download_update.download_update(url=URL, download_dir=tmpdir1, size=URL_len, progressbar=False)
    #if behaving correctly, the downloader should leave a tmpfile with the
    #.done extension in the download directory (tmpdir1)
    assert glob.glob(os.path.join(tmpdir1, marker_regex))
