#!/usr/bin/env python

"""\
$LicenseInfo:firstyear=2006&license=viewerlgpl$
Second Life Viewer Source Code
Copyright (C) 2006-2014, Linden Research, Inc.

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

"""
@file   apply_update.py
@author coyot
@date   2016-06-28
"""

"""
Applies an already downloaded update.
"""

from datetime import datetime
from vmp_util import subprocess_args, SL_Logging, BuildData, put_marker_file

import distutils
from distutils import dir_util

import argparse
import cgitb
import ctypes
import errno
import fnmatch
import glob
import imp
import InstallerUserMessage as IUM
import os
import os.path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

#Module level variables
class ApplyError(Exception):
    def __init__(self, message):
        super(ApplyError, self).__init__(message)
        log = SL_Logging.getLogger("SL_Apply_Update")
        log.error(message)

#fnmatch expressions
LNX_GLOB = '*' + '.bz2'
MAC_GLOB = '*' + '.dmg'
MAC_APP_GLOB = '*' + '.app'
WIN_GLOB = '*' + '.exe'

#which install the updater is run from
INSTALL_DIR = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))

#this is to support pyinstaller, which uses sys._MEIPASS to point to the location
#the bootloader unpacked the bundle to.  If the getattr returns false, we are in a 
#normal Python environment.
if getattr(sys, 'frozen', False):
    __file__ = sys._MEIPASS

def get_filename(download_dir):
    #given a directory that supposedly has the download, find the installable
    #if you are on platform X and you give the updater a directory with an installable  
    #for platform Y, you are either trying something fancy or get what you deserve
    #or both
    for filename in os.listdir(download_dir):
        for glob in LNX_GLOB, MAC_GLOB, WIN_GLOB:
            if (fnmatch.fnmatch(filename, glob)):
                return os.path.join(download_dir, filename)
    #someone gave us a bad directory
    return None  
          
def try_dismount(installable = None, tmpdir = None):
    log = SL_Logging.getLogger("SL_Apply_Update")
    #best effort cleanup try to dismount the dmg file if we have mounted one
    #the French judge gave it a 5.8
    try:
        #use the df command to find the device name
        #Filesystem   512-blocks   Used Available Capacity iused  ifree %iused  Mounted on
        #/dev/disk1s2    2047936 643280   1404656    32%   80408 175582   31%   /private/tmp/mnt/Second Life Installer
        command = ["df", os.path.join(tmpdir, "Second Life Installer")]
        output = subprocess.check_output(command,
                                         **subprocess_args(include_stdout=False,
                                                           log_stream=SL_Logging.stream_from_process(command)))
        log.debug("result of subprocess call to find dmg mount point: %r" % output)
        #No point in trying to umount an fs that doesn't exist. 
        #This could happen, for example, if the user manually umounts it first
        try:
            output.index("Filesystem")
        except ValueError:
            return
        #first word of second line of df output is the device name
        mnt_dev = output.split('\n')[1].split()[0]
        #do the dismount
        command = ["hdiutil", "detach", "-force", mnt_dev]
        output = subprocess.check_output(command,
                                         **subprocess_args(include_stdout=False,
                                                           log_stream=SL_Logging.stream_from_process(command)))
        log.info("result of subprocess call to detach dmg mount point: %r" % output)
        log.info("hdiutil detach succeeded")  
    except Exception, e:
        log.error("Could not detach dmg file %s.  Error messages: %s" % (installable, e.message))  
        #try harder, more forcibly
        try:
            command = ["diskutil", "umount", mnt_dev]
            output = subprocess.check_output(command,
                                                 **subprocess_args(include_stdout=False,
                                                                   log_stream=SL_Logging.stream_from_process(command)))
            log.info("result of subprocess call to unmount dmg mount point: %r" % output)
        except Exception, e:
            log.error("Could not umount dmg file %s.  Error messages: %s" % (installable, e.message))    

def apply_update(download_dir = None, platform_key = None, in_place = True):
    #returns path to newly installed viewer, or None ("don't launch")
    #throws an exception on failure for all three
    installable = get_filename(download_dir)
    if not installable:
        #could not find the download
        raise ValueError("Could not find installable in " + download_dir)
    
    #apply update using the platform specific tools
    if platform_key == 'lnx':
        installed = apply_linux_update(installable, in_place)
    elif platform_key == 'mac':
        installed = apply_mac_update(installable)
    elif platform_key == 'win':
        installed = apply_windows_update(installable)
    else:
        #wtf?
        raise ValueError("Unknown Platform: " + platform_key)
        
    return installed

def apply_linux_update(installable, in_place):
    log = SL_Logging.getLogger("SL_Apply_Update")
    try:
        #untar to tmpdir
        tmpdir = tempfile.mkdtemp()
        tar = tarfile.open(name = installable, mode="r:bz2")
        tar.extractall(path = tmpdir)
        if in_place:
            #rename current install dir
            shutil.move(INSTALL_DIR,install_dir + ".bak")
        #mv new to current
        shutil.move(tmpdir, INSTALL_DIR)
        #delete tarball on success
        os.remove(installable)
    except Exception as e:
        raise ApplyError("Can't install %s: %r" % (installable, e))
    return os.path.join(INSTALL_DIR, "secondlife")

def apply_mac_update(installable):
    log = SL_Logging.getLogger("SL_Apply_Update")

    # TBD - add progress message
    #verify dmg file
    try:
        verify_cmd=["hdiutil", "verify", installable]
        output = subprocess.check_output(verify_cmd, **subprocess_args(include_stdout=False,
                                                                       log_stream=SL_Logging.stream_from_process(verify_cmd)))

        log.info("result of subprocess call to verify dmg file: %r" % output)
        log.info("dmg verification succeeded")
    except Exception as e:
        raise ApplyError("Could not verify dmg file %s.  Error messages: %s" % (installable, e))
    #make temp dir and mount & attach dmg
    tmpdir = tempfile.mkdtemp()
    # TBD - add progress message
    try:
        hdiutil_cmd=["hdiutil", "attach", installable, "-mountroot", tmpdir]
        output = subprocess.check_output(hdiutil_cmd,
                                         **subprocess_args(include_stdout=False,
                                                           log_stream=SL_Logging.stream_from_process(hdiutil_cmd)))
        log.info("result of subprocess call to attach dmg to mount point: %r" % output)
        log.info("hdiutil attach succeeded")
    except Exception as e:
        raise ApplyError("Could not attach dmg file %s.  Error messages: %s" %
                         (installable, e))

    # Now that we've successfully mounted the .dmg, from now on any exit from
    # this function should unmount it.
    try:

        #verify plist
        mounted_appdir = None
        for appdir in glob.glob(os.path.join(tmpdir, '*', MAC_APP_GLOB)):
            try:
                plist = os.path.join(appdir, "Contents", "Info.plist")
                CFBundleIdentifier = plistlib.readPlist(plist)["CFBundleIdentifier"]
                mounted_appdir = appdir
                break
            except:
                #there is no except for this try because there are multiple directories that legimately don't have what we are looking for
                pass
        else:
            raise ApplyError("Could not find app bundle in dmg %s." % (installable,))

        bundle_id = BuildData.get('Bundle Id')
        if CFBundleIdentifier != bundle_id:
            raise ApplyError("Wrong bundle identifier for dmg %s.  "
                             "Bundle identifier: %s, expecting %s" %
                             (installable, CFBundleIdentifier, bundle_id))
        log.debug("Found application directory at %r" % mounted_appdir)

        #do the install, finally       
        #copy over the new bits    
        # TBD - add progress message
        try:
            # in the future, we may want to make this $HOME/Applications ...
            deploy_path = os.path.join("/Applications", os.path.basename(mounted_appdir))
            log.debug("deploy target path: %r" % deploy_path)
            distutils.dir_util.remove_tree(deploy_path)
            output = distutils.dir_util.copy_tree(mounted_appdir,
                                                  deploy_path,
                                                  preserve_mode=1,
                                                  preserve_symlinks=1,
                                                  preserve_times=1)
            #This creates a huge amount of output.  Left as comment for future dev debug, but 
            #should not be in normal use.
            #log.debug("Distutils output: %r" % output)
            # 'output' is a list of copied files, which is why it's reasonable
            # to report len(output)
            log.info("Copied %r files from installer." % len(output))
        except Exception as e:
            raise ApplyError("installation from %s to %s failed: %r" %
                             (installable, deploy_path, e))

    finally:
        # okay, done with mounted .dmg, try to unmount
        try_dismount(installable, tmpdir)

    try:
        # Magic OS directory name that causes Cocoa viewer to crash on OS X 10.7.5
        # (see MAINT-3331)
        STATE_DIR = os.path.join(os.environ["HOME"], "Library", "Saved Application State",
                                 bundle_id + ".savedState")
        shutil.rmtree(STATE_DIR)  
    except OSError as e:
        #if we fail to delete something that isn't there, that's okay
        if e.errno == errno.ENOENT:
            pass
        else:
            raise
    
    os.remove(installable)
    #compute location for viewer launch
    return os.path.join(deploy_path, 'Contents', 'MacOS', 'Second Life')
    
def apply_windows_update(installable):
    log = SL_Logging.getLogger("SL_Apply_Update")

    #This is the point of no return for VMP.  The executable is launched and we exit immediately
    #relying on the NSIS messaging subsystem to warn the resident on error.
    log.info("Launching installer %s." % installable)
    #this is the P_NOWAIT version, returns immediately
    if ctypes.windll.shell32.IsUserAnAdmin():
        log.debug("Launching installer as admin")
        subprocess.Popen(installable, stdin=None, stderr=None)
    else:
        log.debug("Launching installer as user")
        ctypes.windll.shell32.ShellExecuteW(None, u'runas', unicode(installable), "", None, 1)

    #in the Windows case, we launch NSIS and never get a return to check
    #assume that if we got this far, NSIS succeeds
    #put a marker in the dir to signal to update manager to rm the directory on the next run
    put_marker_file(download_dir, ".winstall")

    # Tell SL_Launcher not to run the old viewer -- the installer is still
    # running, and presumably will continue running for some time to come.
    return None

def main():
    parser = argparse.ArgumentParser("Apply Downloaded Update")
    parser.add_argument('--dir', dest = 'download_dir', help = 'directory to find installable', required = True)
    parser.add_argument('--pkey', dest = 'platform_key', help =' OS: lnx|mac|win', required = True)
    parser.add_argument('--in_place', action = 'store_false', help = 'This upgrade is for a different channel', default = True)

    args = parser.parse_args()
   
    result = apply_update(download_dir = args.download_dir, platform_key = args.platform_key,
                          in_place = args.in_place)
    
if __name__ == "__main__":
    cgitb.enable(format='text')
    #this is mostly for testing on Windows, emulating exe enviroment with $python scriptname
    if 'ython' in sys.executable:
        sys.executable =  os.path.abspath(sys.argv[0])
    # Initialize the python logging system to SL Logging format and destination
    # if you are running this manually, not via SL_Launcher, it is assumed you want all logging
    os.environ['SL_LAUNCH_LOGLEVEL'] = 'DEBUG'
    log = SL_Logging.getLogger('SL_Installer')
    try:
        main()
    except Exception:
        log_traceback = cgitb.Hook(file=SL_Logging.stream(prefix_msg="Unhandled exception:"), format='text')
        log_traceback.handle()

