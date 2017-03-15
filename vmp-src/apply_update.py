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

import argparse
import errno
import fnmatch
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

#we only use this for a best effort process cleanup
#if its not there, it doesn't matter.
try:
    if os.name == 'nt':
        import psutil
except:
    pass
    

#Module level variables

#fnmatch expressions
LNX_REGEX = '*' + '.bz2'
MAC_REGEX = '*' + '.dmg'
MAC_APP_REGEX = '*' + '.app'
WIN_REGEX = '*' + '.exe'

#which install the updater is run from
INSTALL_DIR = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))

#whether the update is to the INSTALL_DIR or not.  Most of the time this is the case.
IN_PLACE = True

BUNDLE_IDENTIFIER = "com.secondlife.indra.viewer"

#this is to support pyinstaller, which uses sys._MEIPASS to point to the location
#the bootloader unpacked the bundle to.  If the getattr returns false, we are in a 
#normal Python environment.
if getattr(sys, 'frozen', False):
    __file__ = sys._MEIPASS

def silent_write(log_file_handle, text):
    #if we have a log file, write.  If not, do nothing.
    if (log_file_handle):
        #prepend text for easy grepping
        timestamp = datetime.utcnow().strftime("%m/%d/%Y %H:%M:%S")      
        log_file_handle.write(timestamp + " APPLY UPDATE: " + text + "\n")

def get_filename(download_dir = None):
    #given a directory that supposedly has the download, find the installable
    #if you are on platform X and you give the updater a directory with an installable  
    #for platform Y, you are either trying something fancy or get what you deserve
    #or both
    for filename in os.listdir(download_dir):
        if (fnmatch.fnmatch(filename, LNX_REGEX) 
          or fnmatch.fnmatch(filename, MAC_REGEX) 
          or fnmatch.fnmatch(filename, WIN_REGEX)):            
            return os.path.join(download_dir, filename)
    #someone gave us a bad directory
    return None  
          
def try_dismount(log_file_handle = None, installable = None, tmpdir = None):
    #best effort cleanup try to dismount the dmg file if we have mounted one
    #the French judge gave it a 5.8
    try:
        #use the df command to find the device name
        #Filesystem   512-blocks   Used Available Capacity iused  ifree %iused  Mounted on
        #/dev/disk1s2    2047936 643280   1404656    32%   80408 175582   31%   /private/tmp/mnt/Second Life Installer
        command = ["df", os.path.join(tmpdir, "Second Life Installer")]
        output = subprocess.check_output(command, stdin=None, stdout=log_file_handle, stderr=log_file_handle)
        #No point in trying to umount an fs that doesn't exist. 
        #This could happen, for example, if the user manually umounts it first
        try:
            output.index("No such file or directory")
        except ValueError:
            return
        #first word of second line of df output is the device name
        mnt_dev = output.split('\n')[1].split()[0]
        #do the dismount
        command = ["hdiutil", "detach", "-force", mnt_dev]
        output = subprocess.check_output(command, stdin=None, stdout=log_file_handle, stderr=log_file_handle)
        silent_write(log_file_handle, "hdiutil detach succeeded")
        silent_write(log_file_handle, output)
        command = ["diskutil", "umount", mnt_dev]
        output = subprocess.check_output(command, stdin=None, stdout=log_file_handle, stderr=log_file_handle)
        silent_write(log_file_handle, "diskutil umount succeeded")
        silent_write(log_file_handle, output)        
    except Exception, e:
        silent_write(log_file_handle, "Could not detach dmg file %s.  Error messages: %s" % (installable, e.message))    

def apply_update(download_dir = None, platform_key = None, log_file_handle = None, in_place = True):
    #for lnx and mac, returns path to newly installed viewer
    #for win, return the name of the executable
    #returns None on failure for all three
    #throws an exception if it can't find an installable at all
    
    IN_PLACE = in_place
    
    installable = get_filename(download_dir)
    if not installable:
        #could not find the download
        raise ValueError("Could not find installable in " + download_dir)
    
    #apply update using the platform specific tools
    if platform_key == 'lnx':
        installed = apply_linux_update(installable, log_file_handle)
    elif platform_key == 'mac':
        installed = apply_mac_update(installable, log_file_handle)
    elif platform_key == 'win':
        installed = apply_windows_update(installable, log_file_handle)

        #in the Windows case, we launch NSIS and never get a return to check
        #assume that if we got this far, NSIS succeeds
        #put a marker in the dir to signal to update manager to rm the directory on the next run
        tempfile.mkstemp(suffix=".winstall", dir=os.path.dirname(installable))
    else:
        #wtf?
        raise ValueError("Unknown Platform: " + platform_key)
        
    return installed
    
def apply_linux_update(installable = None, log_file_handle = None):
    try:
        #untar to tmpdir
        tmpdir = tempfile.mkdtemp()
        tar = tarfile.open(name = installable, mode="r:bz2")
        tar.extractall(path = tmpdir)
        if IN_PLACE:
            #rename current install dir
            shutil.move(INSTALL_DIR,install_dir + ".bak")
        #mv new to current
        shutil.move(tmpdir, INSTALL_DIR)
        #delete tarball on success
        os.remove(installable)
    except Exception, e:
        silent_write(log_file_handle, "Update failed due to " + repr(e))
        return None
    return INSTALL_DIR

def apply_mac_update(installable = None, log_file_handle = None):
    #INSTALL_DIR is something like /Applications/Second Life Viewer.app/Contents/MacOS, need to jump up two levels for the install base
    install_base = os.path.dirname(INSTALL_DIR)
    install_base = os.path.dirname(install_base)
    
    #verify dmg file
    try:
        output = subprocess.check_output(["hdiutil", "verify", installable], stdin=None, stdout=log_file_handle, stderr=subprocess.STDOUT)
        silent_write(log_file_handle, "dmg verification succeeded")
        silent_write(log_file_handle, output)
    except Exception, e:
        silent_write(log_file_handle, "Could not verify dmg file %s.  Error messages: %s" % (installable, e.message))
        return None
    #make temp dir and mount & attach dmg
    tmpdir = tempfile.mkdtemp()
    try:
        output = subprocess.check_output(["hdiutil", "attach", installable, "-mountroot", tmpdir], stderr=log_file_handle)
        silent_write(log_file_handle, "hdiutil attach succeeded")
        silent_write(log_file_handle, output)
    except Exception, e:
        silent_write(log_file_handle, "Could not attach dmg file %s.  Error messages: %s" % (installable, e.message))
        return None
    #verify plist
    mounted_appdir = None
    for top_dir in os.listdir(tmpdir):
        for appdir in os.listdir(os.path.join(tmpdir, top_dir)):
            appdir = os.path.join(os.path.join(tmpdir, top_dir), appdir)
            if fnmatch.fnmatch(appdir, MAC_APP_REGEX):
                try:
                    plist = os.path.join(appdir, "Contents", "Info.plist")
                    CFBundleIdentifier = plistlib.readPlist(plist)["CFBundleIdentifier"]
                    mounted_appdir = appdir
                except:
                    #there is no except for this try because there are multiple directories that legimately don't have what we are looking for
                    pass
    if not mounted_appdir:
        silent_write(log_file_handle, "Could not find app bundle in dmg %s." % (installable,))
        return None        
    if CFBundleIdentifier != BUNDLE_IDENTIFIER:
        silent_write(log_file_handle, "Wrong or null bundle identifier for dmg %s.  Bundle identifier: %s" % (installable, CFBundleIdentifier))
        try_dismount(log_file_handle, installable, tmpdir)                   
        return None
    #do the install, finally
    if IN_PLACE:
        #  swap out old install directory
        bundlename = os.path.basename(mounted_appdir)
        silent_write(log_file_handle, "Updating %s" % bundlename)
        swapped_out = os.path.join(tmpdir, INSTALL_DIR.lstrip('/'))
        shutil.move(install_base, swapped_out)               
    else:
        silent_write(log_file_handle, "Installing %s" % install_base)
        
    #   copy over the new bits    
    try:
        shutil.copytree(mounted_appdir, install_base, symlinks=True)
        retcode = 0
    except Exception, e:
        # try to restore previous viewer
        if os.path.exists(swapped_out):
            silent_write(log_file_handle, "Install of %s failed, rolling back to previous viewer." % installable)
            shutil.move(swapped_out, installed_test)
            retcode = 1
    finally:
        try_dismount(log_file_handle, installable, tmpdir)
        if retcode:
            return None
            
    try:
        # Magic OS directory name that causes Cocoa viewer to crash on OS X 10.7.5
        # (see MAINT-3331)
        STATE_DIR = os.path.join(os.environ["HOME"], "Library", "Saved Application State",
            BUNDLE_IDENTIFIER + ".savedState")
        shutil.rmtree(STATE_DIR)  
    except Exception, e:
        #if we fail to delete something that isn't there, that's okay
        if e[0] == errno.ENOENT:
            pass
        else:
            raise e
    
    os.remove(installable)
    return install_base
    
def apply_windows_update(installable = None, log_file_handle = None):
    #the windows install is just running the NSIS installer executable
    #from VMP's perspective, it is a black box
    kill_em_all(2)

    #This is the point of no return for VMP.  The executable is launched and we exit immediately
    #relying on the NSIS messaging subsystem to warn the resident on error.
    silent_write(log_file_handle, "Launching installer %s." % installable)
    #this is the P_NOWAIT version, returns immediately
    subprocess.Popen(installable, stdin=None, stdout=log_file_handle, stderr=log_file_handle)
    return os.path.dirname(installable)

def kill_em_all(level):
    #go up the process subtree level number of parent levels and then kill all processes under that root except the current process
    my_pid = os.getpid()
    curr = my_pid
    root = psutil.Process(curr)

    #walk up the tree, range stops at level - l, and parent(level - 1) is what we want
    #for a tree of depth n, this is an O(n) search
    for n in range(1, level):
        curr = root.ppid()
        root = psutil.Process(curr)
    
    children = root.children(recursive=True)
    #this search is O(m) for m nodes (m >= n) in the flattened tree we get back from children()
    for process in children:
        #only the caller survives the horror
        if psutil.pid_exists(process.pid):
            if process.pid != my_pid:
                process.send_signal(signal.SIGTERM)

def main():
    parser = argparse.ArgumentParser("Apply Downloaded Update")
    parser.add_argument('--dir', dest = 'download_dir', help = 'directory to find installable', required = True)
    parser.add_argument('--pkey', dest = 'platform_key', help =' OS: lnx|mac|win', required = True)
    parser.add_argument('--in_place', action = 'store_false', help = 'This upgrade is for a different channel', default = True)
    parser.add_argument('--log_file', dest = 'log_file', default = None, help = 'file to write messages to')
    args = parser.parse_args()
    
    if args.log_file:
        try:
            f = open(args.log_file,'w+') 
        except:
            print "%s could not be found or opened" % args.log_file
            sys.exit(1)
    
    IN_PLACE = args.in_place
    result = apply_update(download_dir = args.download_dir, platform_key = args.platform_key, log_file_handle = f)
    if not result:
        sys.exit("Update failed")
    else:
        sys.exit(0)


if __name__ == "__main__":
   #this is mostly for testing on Windows, emulating exe enviroment with $python scriptname
   if 'ython' in sys.executable:
      sys.executable =  os.path.abspath(sys.argv[0])   
   main()
