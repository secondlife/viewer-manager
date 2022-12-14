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

from util import subprocess_args, pass_logger, SL_Logging, BuildData, Application

from contextlib import suppress
import errno
import glob
import InstallerUserMessage as IUM
import itertools
import os
import os.path
from pathlib import Path
import plistlib
from runner import Runner, ExecRunner
import shutil
import subprocess
import tarfile
import tempfile

#Module level variables
class ApplyError(Exception):
    def __init__(self, message):
        super(ApplyError, self).__init__(message)
        log = SL_Logging.getLogger("SL_Apply_Update")
        log.error(message)

#fnmatch expressions
LNX_GLOB     = '*.bz2'
MAC_GLOB     = '*.dmg'
MAC_APP_GLOB = '*.app'
WIN_GLOB     = '*.exe'

@pass_logger
def get_filename(log, download_dir):
    #given a directory that supposedly has the download, find the installable
    #if you are on platform X and you give the updater a directory with an installable  
    #for platform Y, you are either trying something fancy or get what you deserve
    #or both
    matches = list(itertools.chain(*(glob.glob(os.path.join(download_dir, pattern))
                                     for pattern in (LNX_GLOB, MAC_GLOB, WIN_GLOB))))
    if len(matches) == 1:
        # perfect, just what we wanted!
        return matches[0]

    log.error("%s installers in '%s': %s",
              ("Ambiguous" if matches else "No"), download_dir, matches)
    return None
          
def try_dismount(installable, tmpdir):
    log = SL_Logging.getLogger("SL_Apply_Update")
    #best effort cleanup try to dismount the dmg file if we have mounted one
    #the French judge gave it a 5.8
    try:
        #use the df command to find the device name
        #Filesystem   512-blocks   Used Available Capacity iused  ifree %iused  Mounted on
        #/dev/disk1s2    2047936 643280   1404656    32%   80408 175582   31%   /private/tmp/mnt/Second Life Installer
        command = ["df", os.path.join(tmpdir, "Second Life Installer")]
        output = subprocess.check_output(
            command,
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
        subprocess.check_call(
            command,
            **subprocess_args(log_stream=SL_Logging.stream_from_process(command)))
        log.info("hdiutil detach succeeded")  
    except Exception as e:
        log.error("Could not detach dmg file %s.  Error messages: %s" % (installable, e))  
        #try harder, more forcibly
        try:
            command = ["diskutil", "umount", mnt_dev]
            subprocess.check_call(
                command,
                **subprocess_args(log_stream=SL_Logging.stream_from_process(command)))
        except Exception as e:
            log.error("Could not umount dmg file %s.  Error messages: %s" % (installable, e))    

def apply_update(runner, installable, platform_key):
    #apply update using the platform specific tools
    try:
        apply_platform_update = dict(
            lnx=apply_linux_update,
            mac=apply_mac_update,
            win=apply_windows_update,
            )[platform_key]
    except KeyError:
        raise ApplyError("Unknown Platform: " + platform_key)

    return apply_platform_update(runner, installable)

def apply_linux_update(runner, installable):
    # UNTESTED
    log = SL_Logging.getLogger("SL_Apply_Update")
    IUM.safe_status_message("Installing from tarball...", ApplyError)
    
    #which install the updater is run from
    install_dir = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
    try:
        #untar to tmpdir
        tmpdir = tempfile.mkdtemp()
        tar = tarfile.open(name = installable, mode="r:bz2")
        tar.extractall(path = tmpdir)
        #rename current install dir
        shutil.move(install_dir,install_dir + ".bak")
        #mv new to current
        shutil.move(tmpdir, install_dir)
        #delete tarball on success
        os.remove(installable)
    except Exception as e:
        raise ApplyError("Can't install %s: %r" % (installable, e))

    # return the original runner, which should work as-is since the new viewer
    # is at the same pathname as the old
    return runner

def apply_mac_update(runner, installable):
    log = SL_Logging.getLogger("SL_Apply_Update")

    #verify dmg file
    IUM.safe_status_message("Verifying installer image...", ApplyError)
    
    try:
        verify_cmd=["hdiutil", "verify", installable]
        # log both stdout and stderr to our log file
        subprocess.check_call(
            verify_cmd,
            **subprocess_args(log_stream=SL_Logging.stream_from_process(verify_cmd)))
        log.info("dmg verification succeeded")
    except Exception as e:
        raise ApplyError("Could not verify dmg file %s.  Error messages: %r" % (installable, e))
    #make temp dir and mount & attach dmg
    tmpdir = tempfile.mkdtemp()

    # Now that we've created the mount-point directory, from now on any exit
    # from this function should remove it.
    try:

        IUM.safe_status_message("Mounting installer image...", ApplyError)
            
        try:
            hdiutil_cmd=["hdiutil", "attach", installable, "-mountroot", tmpdir]
            # log both stdout and stderr to our log file
            subprocess.check_call(
                hdiutil_cmd,
                **subprocess_args(log_stream=SL_Logging.stream_from_process(hdiutil_cmd)))
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
                plist = os.path.join(appdir, "Contents", "Info.plist")
                # there are multiple directories that legimately don't have
                # what we are looking for
                with suppress(IOError, KeyError):
                    with open(plist, 'rb') as plf:
                        CFBundleIdentifier = plistlib.load(plf)["CFBundleIdentifier"]
                    # we only reach this point if open(), load() and [] succeed
                    mounted_appdir = appdir
                    break
            else:
                raise ApplyError("Could not find app bundle in dmg %s." % (installable,))

            bundle_id = BuildData.get('Bundle Id')
            if CFBundleIdentifier != bundle_id:
                raise ApplyError("Wrong bundle identifier for dmg %s.  "
                                 "Bundle identifier: %s, expecting %s" %
                                 (installable, CFBundleIdentifier, bundle_id))
            log.debug("Found application directory at '%s'", mounted_appdir)

            IUM.safe_status_message("Removing old viewer...", ApplyError)

            # in the future, we may want to make this $HOME/Applications ...
            deploy_path = os.path.join("/Applications", os.path.basename(mounted_appdir))
            log.debug("deploy target path: %r" % deploy_path)
            try:
                shutil.rmtree(deploy_path)
            except FileNotFoundError as e:
                #if we fail to delete something that isn't there, that's okay
                pass
            except OSError as e:
                raise ApplyError("failed to remove existing install %s: %r" % (deploy_path, e))

            # How many files will we try to copy from mounted_appdir? Count
            # only files because shutil.copytree()'s copy_function is only
            # called for files. Don't count symlinks (even though is_file()
            # returns True for a symlink to a file) because copy_function
            # isn't called for them either. Rather than collecting all paths
            # into a list and then taking its len(), count them on the fly.
            total = sum(1 for f in Path(mounted_appdir).rglob('*')
                        if f.is_file() and not f.is_symlink())
            log.debug("%s files in application directory tree", total)

            #do the install, finally       
            #copy over the new bits
            with IUM.intercept_close(ApplyError,
                                     'installation from %s to %s failed' %
                                     (installable, deploy_path)), \
                 ProgressCopyTree("Copying updated viewer...", total) as copier:
                # Specifying our ProgressCopyTree as the copy_function
                # lets us tick the progress bar every time we copy a file.
                shutil.copytree(mounted_appdir,
                                deploy_path,
                                symlinks=True,
                                copy_function=copier)
                # grab count of files copied before copier goes out of scope
                copied = copier.count

            IUM.safe_status_message("Copied %r files from installer." % copied)

        finally:
            # okay, done with mounted .dmg, try to unmount
            try_dismount(installable, tmpdir)

    finally:
        # done with temporary mount-point directory
        try:
            os.rmdir(tmpdir)
        except OSError as e:
            log.warning("failed to clean up temporary mount point %r: %r", tmpdir, e)
            # but carry on: we may be in the middle of processing some OTHER
            # exception; don't let this one discard that one

    #if we fail to delete something that isn't there, that's okay
    with suppress(FileNotFoundError):
        # Clean up viewer saved state 
        # (see MAINT-3331; this caused a crash on OSX 10.7.5)
        STATE_DIR = os.path.expanduser(os.path.join("~/Library", "Saved Application State",
                                                    bundle_id + ".savedState"))
        shutil.rmtree(STATE_DIR)  
    
    os.remove(installable)
    # replace the original executable in the command, but pass through all
    # remaining command-line arguments
    # we can't just exec the .app
    return ExecRunner('/usr/bin/open', deploy_path, '--args', *runner.command()[1:])
    # Alternatively:
    # return ExecRunner(os.path.join(deploy_path, "Contents", "MacOS", "SecondLife"),
    #                   *runner.command()[1:])

class ProgressCopyTree:
    def __init__(self, message, total):
        self.message = message
        self.total = total
        self.count = 0

    def __enter__(self):
        # display the progress bar
        IUM.root().progress_bar(self.message, self.total)
        return self

    def __call__(self, source, dest):
        shutil.copy2(source, dest)
        IUM.root().step(1)
        self.count += 1

    def __exit__(self, *exc_info):
        IUM.root().progress_done()
        # do not swallow exceptions
        return False

def apply_windows_update(runner, installable):
    IUM.safe_status_message("Launching installer...", ApplyError)
    # Pass back the installer; SL_Launcher will exec it and replace this process.
    # Ignore all command-line arguments; we can't pass them through the NSIS
    # installer to the next viewer anyway.
    # Direct the NSIS installer to create a marker file for cleanup next run.
    # Suppress the DOS box window.
    return ExecRunner(installable, "/marker", window=False)

def main():
    import argparse
    parser = argparse.ArgumentParser("Apply Downloaded Update")
    parser.add_argument('--dir', dest = 'download_dir', help = 'directory to find installable', required = True)
    parser.add_argument('--pkey', dest = 'platform_key', help =' OS: lnx|mac|win', required = True)

    args = parser.parse_args()
   
    result = apply_update(Runner("ignored"), download_dir = args.download_dir,
                          platform_key = args.platform_key)
    
if __name__ == "__main__":
    # Initialize the python logging system to SL Logging format and destination
    # if you are running this manually, not via SL_Launcher, it is assumed you want all logging
    os.environ['SL_LAUNCH_LOGLEVEL'] = 'DEBUG'
    SL_Logging.getLogger('SL_Installer')
    main()
