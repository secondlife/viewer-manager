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
@file   update_manager.py
@author coyot
@date   2016-06-23
"""

from copy import deepcopy
from datetime import datetime
from llbase import llrest
from llbase.llrest import RESTError
from llbase import llsd    
from urlparse import urljoin
from vmp_util import SL_Logging, subprocess_args

import apply_update
import download_update
import errno
import fnmatch
import hashlib
import InstallerUserMessage
import json
import os
import os.path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import thread
import time
import urllib

#module global
download_process = None

#this is a trick stolen from shutil.py.  WindowsError is not defined on POSIX implementations 
#of python and will throw a NameError when make_download_dir() tries to catch it for the times
#it is on Windows.  This sets the exception to a dummy value if WindowsError is not already defined.
try:
    WindowsError
except NameError:
    WindowsError = None

#this is to support pyinstaller, which uses sys._MEIPASS to point to the location
#the bootloader unpacked the bundle to.  If the getattr returns false, we are in a 
#normal Python environment.
if getattr(sys, 'frozen', False):
    __file__ = sys._MEIPASS

def after_frame(message, timeout = 10000):
    #pop up a InstallerUserMessage.basic_message that kills itself after timeout milliseconds
    #note that this blocks the caller for the duration of timeout
    frame = InstallerUserMessage.InstallerUserMessage(title = "Second Life Installer", icon_name="head-sl-logo.gif")
    #this is done before basic_message so that we aren't blocked by mainloop()
    frame.after(timeout, lambda: frame.destroy())
    frame.basic_message(message = message)

def md5file(fname=None, handle=None):
    #utility method to compute the checksum of the contents of a file
    hash_md5 = hashlib.md5()
    if fname is not None:
        with open(fname, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
    #unit tests use tempfile temporary files which return handles to files that vanish if you
    #close the handle while Windows will say permission denied to a second handle.
    elif handle is not None:
        for chunk in iter(lambda: handle.read(4096), b""):
            hash_md5.update(chunk)
    else:
        return None
    return hash_md5.hexdigest()

def convert_version_file_style(version):
    #converts a version string a.b.c.d to a_b_c_d as used in downloaded filenames
    #re will throw a TypeError if it gets None, just return that.
    try:
        pattern = re.compile('\.')
        return pattern.sub('_', version)
    except TypeError, te:
        return None

def get_platform_key():
    #this is the name that is inserted into the VVM URI
    #and carried forward through the rest of the updater to determine
    #platform specific actions as appropriate
    platform_dict = {'Darwin':'mac', 'Linux':'lnx', 'Windows':'win'}
    platform_uname = platform.system()
    try:
        return platform_dict[platform_uname]
    except KeyError:
        return None

def get_summary(platform_name):
    #get the contents of the summary.json file.
    #for linux and windows this file is in the same directory as the script
    #for mac, the script is in ../Contents/MacOS/ and the file is in ../Contents/Resources/
    if (platform_name == 'mac'):
        summary_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../Resources"))
    else:
        summary_dir = os.path.abspath(os.path.dirname(str(sys.executable)))
    summary_file = os.path.join(summary_dir,"summary.json")
    #for windows unit tests
    if not os.path.exists(summary_file):
        summary_file = os.path.join(os.path.dirname(apply_update.__file__), "tests", "summary.json")
        if not os.path.exists(summary_file):
            return None
    with open(summary_file) as summary_handle:
        return json.load(summary_handle)

def get_parent_path(platform_name):
    #find the parent of the logs and user_settings directories
    if (platform_name == 'mac'):
        settings_dir = os.path.join(os.path.expanduser('~'),'Library','Application Support','SecondLife')
    elif (platform_name == 'lnx'): 
        settings_dir = os.path.join(os.path.expanduser('~'),'.secondlife')
    #using list format of join is important here because the Windows pathsep in a string escapes the next char
    elif (platform_name == 'win'):
        settings_dir = os.path.join(os.path.expanduser('~'),'AppData','Roaming','SecondLife')
    else:
        settings_dir = None
    return settings_dir

def make_download_dir(parent_dir, new_version):
    #make a canonical download dir if it does not already exist
    #format: ../user_settings/downloads/1.2.3.456789
    #we do this so that multiple viewers on the same host can update separately
    #this also functions as a getter 
    try:
        download_dir = os.path.join(parent_dir, "downloads", new_version)
        os.makedirs(download_dir)
    except (OSError, WindowsError) as hell:
        #Directory already exists, that's okay.  Other OSErrors are not okay.
        if hell.errno == errno.EEXIST and os.path.isdir(download_dir): 
            pass
        else:
            raise
    return download_dir

def check_for_completed_download(download_dir, expected_size = 0):
    #there will be two files on completion, the download and a marker file called "".done""
    #for optional upgrades, there may also be a .skip file to skip this particular upgrade 
    #or a next file which defers the choice to the next startup.
    if not os.path.exists(download_dir):
        return None
    completed = 'initialized'
    marker_regex = '*' + '.done'
    skip_regex = '*' + '.skip'
    next_regex = '*' + '.next'
    win_regex = '*' + '.winstall'
    installer = None
    #We don't know what order the files will be seen in the loop.  Done has the least priority,
    #next is second and skip is highest.  That is, if the resident said skip, never ask again.  
    #While we are here, grab the name of the installer so we can hash the file later
    for filename in os.listdir(download_dir):
        if fnmatch.fnmatch(filename, win_regex):
            return 'winstall'
        elif fnmatch.fnmatch(filename, marker_regex):
            #we could have both skip and done files, if so, return skip
            if completed == 'initialized':
                completed = 'done'
        elif fnmatch.fnmatch(filename, skip_regex):
            completed = 'skip'
        elif fnmatch.fnmatch(filename, next_regex) and completed != 'skip':
            completed = 'next'
        else:
            installer = filename
    #we found some sort of partial remnants of a download
    if completed == 'initialized':
        if installer is not None:
            installer = os.path.join(download_dir, installer)
            if os.path.exists(installer):
                #the theory of operation is that if the file hasn't changed in ten seconds
                #there is no download in progress
                first_sample = os.path.getsize(installer)
                time.sleep(10)
                second_sample = os.path.getsize(installer)
                if (second_sample > first_sample) and (second_sample != expected_size):
                    #this is a protocol hack.  The caller will see this and interpret the download
                    #in progress as an optional update to be ignored.  Later, when done, a later launch
                    #instance will see the completed download and act accordingly.
                    return 'skip'
        else:
            #cleanup the mess, start over next time
            shutil.rmtree(download_dir)
            return None
    return completed  

def get_settings(parent_dir):
    #return the settings file parsed into a dict
    settings=None
    log=SL_Logging.getLogger('get_settings')
    try:
        settings_file = os.path.abspath(os.path.join(parent_dir,'user_settings','settings.xml'))
        #this happens when the path to settings file happens on the command line
        #we get a full path and don't need to munge it
        if not os.path.exists(settings_file):
            settings_file = parent_dir
        settings = llsd.parse((open(settings_file)).read())
    except llsd.LLSDParseError as lpe:
        log.warning("Could not parse settings file %s" % lpe)
    except Exception as e:
        log.warning("Could not read settings file %s" % e)
    return settings

def make_VVM_UUID_hash(platform_key):
    log = SL_Logging.getLogger('make_VVM_UUID_hash')

    #NOTE: There is no python library support for a persistent machine specific UUID (MUUID)
    #      AND all three platforms do this a different way, so exec'ing out is really the best we can do
    #Lastly, this is a best effort service.  If we fail, we should still carry on with the update 
    muuid = None
    #for env without stdin, such as pythonw and pyinstaller, provide a legit empty handle, not the broken
    #thing we get from the env.
    if (platform_key == 'lnx'):
        hostid_cmd=['/usr/bin/hostid']
        muuid = subprocess.check_output(hostid_cmd,
                                        **subprocess_args(include_stdout=False,
                                                          log_stream=SL_Logging.stream(hostid_cmd)
                                                          )).rstrip()
        log.debug("result of subprocess call to get linux MUUID: %r" % muuid)
    elif (platform_key == 'mac'):
        #this is absurdly baroque
        #/usr/sbin/system_profiler SPHardwareDataType | fgrep 'Serial' | awk '{print $NF}'
        profiler_cmd=["/usr/sbin/system_profiler", "SPHardwareDataType"]
        muuid = subprocess.check_output(profiler_cmd, **subprocess_args(include_stdout=False, log_stream=SL_Logging.stream(profiler_cmd)))
        #findall[0] does the grep for the value we are looking for: "Serial Number (system): XXXXXXXX"
        #split(:)[1] gets us the XXXXXXX part
        #lstrip shaves off the leading space that was after the colon
        muuid = re.split(":", re.findall('Serial Number \(system\): \S*', muuid)[0])[1].lstrip()
        log.debug("result of subprocess call to get mac MUUID: %r" % muuid)
    elif (platform_key == 'win'):
        # wmic csproduct get UUID | grep -v UUID
        wmic_cmd=['wmic','csproduct','get','UUID']
        muuid = subprocess.check_output(wmic_cmd, **subprocess_args(include_stdout=False,log_stream=SL_Logging.stream(wmic_cmd)))
        #outputs in two rows:
        #UUID
        #XXXXXXX-XXXX...
        muuid = re.split('\n',muuid)[1].rstrip()
        log.debug("result of subprocess call to get win MUUID: %r" % muuid)
            
    if muuid is not None:
        hash = hashlib.md5(muuid).hexdigest()
    else:
        #fake it
        log.info("Unable to get system unique id; constructing a dummy")
        hash = hashlib.md5(str(uuid.uuid1())).hexdigest()
    return hash

def getBitness(platform_key = None):
    log=SL_Logging.getLogger('getBitness')
    if platform_key in ['lnx', 'mac']:
        return 64
    if 'PROGRAMFILES(X86)' not in os.environ:
        return 32
    else:
        #see MAINT-6832 and IQA-4130
        wmic_cmd=['wmic','path','Win32_VideoController','get','NAME']
        wmic_graphics = subprocess.check_output(wmic_cmd, **subprocess_args(include_stdout=False, log_stream=SL_Logging.stream(wmic_cmd)))
        log.debug("result of subprocess call to get wmic graphics card info: %r" % muuid)
        wmic_list = re.split('\n', wmic_graphics)
        bad = False
        for word in wmic_list:
            if word.find("Intel(R) HD Graphics") > -1:
                bad = True
                log.info("Setting bitness to 32 due to HD Graphics Win 64 Bit incompatibility.")
                return 32
        return 64
    
def isViewerMachineBitMatched(viewer_platform = None, platform_key = None, bitness = 64):
    if not viewer_platform or not platform_key:
        return False
    #viewer_platform in (lnx, mac, win, win32)
    #platform_key in (lnx, mac, win)
    if (viewer_platform == 'lnx' and platform_key == 'lnx') or (viewer_platform == 'mac' and platform_key == 'mac'):
        return True
    #this happens if you try to install the viewer on the wrong OS: either lnx != lnx, mac != mac or win != either of those
    if viewer_platform not in ['win', 'win32'] or platform_key != 'win':
        return False
    #default is to ship 64 bit
    win_plat_key = 'win'
    if bitness == 32:
        win_plat_key = 'win32'
    return (viewer_platform == win_plat_key)

def query_vvm(platform_key = None, settings = None, summary_dict = None, UpdaterServiceURL = None, UpdaterWillingToTest = None):
    result_data = None
    baseURI = None
    VMM_platform = platform_key
    log=SL_Logging.getLogger('query_vvm')
    #to disambiguate, we have two sources of platform here
    #  platform_key is the OS name of the computer VMP is running on
    #  summary_dict['platform'] is the platform and for windows, bitness, of the _viewer_ that VMP is part of
    #These are not always the same, in particular, for the first download of a VMP windows viewer which defaults to 64 bit
    bitness = getBitness(platform_key)
    try:
        if not isViewerMachineBitMatched(summary_dict['Platform'], platform_key, bitness):
            #there are two cases:
            # the expected case where we downloaded a 64 bit viewer to a 32 bit machine on spec
            # the unexpected case where someone was running a 32 bit viewer on a 32 bit Windows box and upgraded their Windows to 64 bit
            #either way, the Windows bitness is the right bitness
            if bitness == 32:
                VMM_platform = 'win32'
    except Exception as e:
        log.warning("Could not parse viewer bitness from summary.json %r" % e)
        #At these point, we have no idea what is really going on.  Since 32 installs on 64 and not vice-versa, fall back to safety
        VMM_platform = 'win32'        
    
    #URI template /update/v1.1/channelname/version/platformkey/platformversion/willing-to-test/uniqueid
    #https://wiki.lindenlab.com/wiki/Viewer_Version_Manager_REST_API#Viewer_Update_Query
    #note that the only two valid options are:
    # # version-phx0.damballah.lindenlab.com
    # # version-qa.secondlife-staging.com
    if UpdaterServiceURL:
        #we can't really expect the users to put the protocol or base dir on, they will give us a host
        base_URI = urljoin('http://' + UpdaterServiceURL[0], '/update/')
    else:
        base_URI = 'https://update.secondlife.com/update/'
    channelname = str(summary_dict['Channel'])
    pattern = re.compile('\'|\[|\]')
    channelname = pattern.sub('', channelname)    
    version = summary_dict['Version']
    #we need to use the dotted versions of the platform versions in order to be compatible with VVM rules and arithmetic
    if platform_key == 'win':
        platform_version = platform.win32_ver()[1]
    elif platform_key == 'mac':
        platform_version = platform.mac_ver()[0]
    else:
        platform_version = platform.release()
    #this will always return something usable, error handling in method
    UUID = str(make_VVM_UUID_hash(platform_key))
    #note that this will not normally be in a settings.xml file and is only here for test builds.
    #for test builds, add this key to the ../user_settings/settings.xml
    """
        <key>test</key>
        <map>
        <key>Comment</key>
            <string>Tell update manager you aren't willing to test.</string>
        <key>Type</key>
            <string>String</string>
        <key>Value</key>
            <integer>testno</integer>
        </map>
    </map>
    """
    if UpdaterWillingToTest is not None and UpdaterWillingToTest == 'testok':
        test_ok = 'testok'
    elif re.search('^Second Life Test', channelname) is not None:
        test_ok = 'testno'
    else:   
        try:
            test_ok = settings['test']['Value']
        except Exception:
            #normal case, no testing key
            test_ok = 'testok'
    #because urljoin can't be arsed to take multiple elements
    #channelname is a list because although it is only one string, it is a kind of argument and viewer args can take multiple keywords.
    log.info("Requesting update for channel '%s' version %s platform %s platform version %s allow_test %s id %s" %
             (str(channelname), version, VMM_platform, platform_version, test_ok, UUID))
    query_string =  urllib.quote('v1.1/' + str(channelname) + '/' + version + '/' + VMM_platform + '/' + platform_version + '/' + test_ok + '/' + UUID)
    log.debug("Sending query to VVM: %s" % base_URI + query_string)
    VVMService = llrest.SimpleRESTService(name='VVM', baseurl=base_URI)
    try:
        result_data = VVMService.get(query_string)
    except RESTError as res:
        if res.status != 404: # 404 is how the Viewer Version Manager indicates no-update
            log.warning("Failed to query VVM using %s failed as %s" % (urljoin(base_URI,query_string), res))
        return None
    return result_data

def download(url = None, version = None, download_dir = None, size = 0, hash = None, background = False, chunk_size = None):
    log=SL_Logging.getLogger('download')
    download_tries = 0
    download_success = False
    download_process = None
    download_process_args = None
    if not chunk_size:
        chunk_size = 5*1024
    #for background execution
    if get_platform_key() == 'win':
        path_to_downloader = os.path.join(os.path.dirname(os.path.realpath(sys.executable)), "download_update.exe")
    else:
        path_to_downloader = os.path.join(os.path.dirname(os.path.realpath(__file__)), "download_update.py")

    #three strikes and you're out
    log.info("Preparing to download new version " + version + " destination " + download_dir + ".")
    while download_tries < 3 and not download_success:
        #323: Check for a partial update of the required update; in either event, display an alert that a download is required, initiate the download, and then install and launch
        if not background:
            log.debug("foreground downloader args: %r" % ["--url", url, "--dir", download_dir, 
                            "--size", str(size), "--chunk_size", str(chunk_size)])
            if download_tries == 0:
                after_frame(message = "Downloading new version " + version + " Please wait.", timeout = 5000)
            else:
                after_frame(message = "Trying again to download new version " + version + " Please wait.", timeout = 5000)
            try:
                download_update.download_update(url = url, download_dir = download_dir, size = size, progressbar = True, chunk_size = chunk_size)
                download_success = True
            except Exception as e:
                download_tries += 1    
                log.warning("Failed to download new version " + version + " in foreground downloader. Trying again.")
                log.error("Logging download exception: %r" % e)
            #check to make sure the downloaded file is correct
            filename = os.path.join(download_dir, url.split('/')[-1])
            down_hash = md5file(filename)
            if down_hash != hash:
                #try again
                download_tries += 1
                download_success = False
                log.warning("Hash mismatch: Expected: %s Received: %s" % (hash, down_hash))
        else:
            try:
                #Python does not have a facility to multithread a method, so we make the method a standalone script
                #and subprocess that.  The business with the file descriptors is how to tell subprocess not to wait.
                #since we are using Popen and not check_output, subprocess_args isn't needed
                #arguments to execv() via popen() can only be strings, hence str(int)
                downloader_cmd = ["path to downloader", path_to_downloader,
                                  "--url", url,
                                  "--dir", download_dir, 
                                  "--size", str(size),
                                  "--chunk_size", str(chunk_size)]
                log.debug("background downloader args: %r" % downloader_cmd)
                log_stream = SL_Logging.stream(downloader_cmd, streamname="stdout and stderr")
                download_process = subprocess.Popen(downloader_cmd,
                                                    **subprocess_args(include_stdout=True, log_stream=log_stream)
                                                    )
                log.debug("Download of new version " + version + " spawned.")
                download_success = True
            except  Exception, e:
                download_tries += 1
                download_success = False
                log.debug("Logging download exception: %r, subprocess returned: %r" % (e, download_process))
                log.warning("Failed to download new version in background downloader " + version + ". Trying again.")

    if not download_success:
        log.warning("Failed to download new version " + version + " from " + str(url) + " Please check connectivity.")
        if not background:
            after_frame(message = "Failed to download new version " + version + " from " + str(url) + " Please check connectivity.")
        return False    
    
    #cleanup, so that we don't download twice
    for filename in os.listdir(download_dir):
        if fnmatch.fnmatch(filename, '*' + '.next'):
            os.remove(os.path.join(download_dir, filename))

    if download_process_args is not None:
        log.debug("Returning downloader process args: %r" % download_process_args)
        return download_process_args
    else:
        return True

def install(platform_key = None, download_dir = None, in_place = None, downloaded = None):
    log=SL_Logging.getLogger('install')
    #user said no to this one
    if downloaded != 'skip':
        after_frame(message = "New version downloaded.\nInstalling now, please wait.")
        success = apply_update.apply_update(download_dir, platform_key, in_place)
        version = download_dir.split('/')[-1]
        if success:
            log.info("successfully updated to " + version)
            #windows is cleaned up on the following run, see apply_update.apply_update()
            if platform_key != 'win':
                shutil.rmtree(download_dir)
            #this is either True for in place or the path to the new install for not in place
            return success
        else:
            after_frame(message = "Failed to apply " + version)
            log.warning("Failed to update viewer to " + version)
            return False
        
def download_and_install(downloaded = None, url = None, version = None, download_dir = None, size = None, 
                        hash = None, platform_key = None, in_place = None, chunk_size = 1024):
    #extracted to a method because we do it twice in update_manager() and this makes the logic clearer
    #also, mandatory downloads ignore the distinction between skip and done, either result means we are gtg
    if downloaded is None:
        #do the download, exit if we fail
        if not download(url = url, version = version, download_dir = download_dir, size = size, background = False,
                        hash = hash, chunk_size = chunk_size): 
            return (False, 'download', version)  
    #do the install
    path_to_new_launcher = install(platform_key = platform_key, download_dir = download_dir, 
                                   in_place = in_place, downloaded = downloaded)
    if path_to_new_launcher:
        #if we succeed, propagate the success type upwards
        if in_place:
            return (True, 'in place', True)
        else:
            return (True, 'in place', path_to_new_launcher)
    else:
        #propagate failure
        return (False, 'apply', version)    
            

def update_manager(cli_overrides = None):
    log = SL_Logging.getLogger('update_manager')
    log.debug("%r", cli_overrides)

    #cli_overrides is a dict where the keys are specific parameters of interest and the values are the arguments to 
    #comments that begin with '323:' are steps taken from the algorithm in the description of SL-323. 
    #  Note that in the interest of efficiency, such as determining download success once at the top
    #  The code does follow precisely the same order as the algorithm.
    #return values rather than exit codes.  All of them are to communicate with launcher
    #we print just before we return so that __main__ outputs something - returns are swallowed
    #  (False, 'setup', None): error occurred before we knew what the update was (e.g., in setup or parsing)
    #  (False, 'download', version): we failed to download the new version
    #  (False, 'apply', version): we failed to apply the new version
    #  (True, None, None): No update found
    #  (True, 'in place', True): update applied in place
    #  (True, 'in place', path_to_new_launcher): Update applied by a new install to a new location
    #  (True, 'background', popen_object): background download initiated, object passed to wait on
    #  (True, 'skip', True): User has chosen to skip this optional update

    #setup and getting initial parameters
    platform_key = get_platform_key()
    parent_dir = get_parent_path(platform_key)
    settings = None

    #check to see if user has install rights
    #get the owner of the install and the current user
    #none of this is supported by Python on Windows
    try:
        script_owner_id = os.stat(os.path.realpath(__file__)).st_uid
        user_id = os.getuid()
        if script_owner_id != user_id:
            import pwd
            script_owner_name = pwd.getpwuid(script_owner_id)[0]
            username = pwd.getpwuid(user_id)[0]
            log.info("Upgrade notification attempted by userid " + username)    
            frame = InstallerUserMessage.InstallerUserMessage(title = "Second Life Installer", icon_name="head-sl-logo.gif")
            frame.binary_choice_message(message = "Second Life was installed by userid " + script_owner_name 
                + ".  Do you have privileges to install?", true = "Yes", false = 'No')
            if not frame.choice.get():
                log.info("Upgrade attempt declined by userid " + username)
                after_frame(message = "Please find a system admin to upgrade Second Life")
                log.debug("Update manager exited with (Success = %s, Stage = %s)" % (False, 'setup'))
                return (False, 'setup', None)
    except (AttributeError, ImportError):
        #Windows throws AttributeError on getuid() and ImportError on pwd
        #Just ignore it and consider the ID check as passed.
        pass

    settings = get_settings(parent_dir)
    if cli_overrides is not None: 
        if 'settings' in cli_overrides.keys():
            if cli_overrides['settings'] is not None:
                settings = get_settings(cli_overrides['settings'][0])
        
    if settings is None:
        log.warning("Failed to load viewer settings from " 
                     +  os.path.abspath(os.path.join(parent_dir,'user_settings','settings.xml')))
        log.debug("Update manager exited with (Success = %s, Stage = %s)" % (False, 'setup'))
        return (False, 'setup', None)

    #323: If a complete download of that update is found, check the update preference:
    #settings['UpdaterServiceSetting'] = 0 is manual install
    """
    <key>UpdaterServiceSetting</key>
        <map>
        <key>Comment</key>
            <string>Configure updater service.</string>
        <key>Type</key>
            <string>U32</string>
        <key>Value</key>
            <string>0</string>
        </map>
    """
    if cli_overrides is not None: 
        if 'set' in cli_overrides.keys():
            if 'UpdaterServiceSetting' in cli_overrides['set'].keys():
                install_automatically = cli_overrides['set']['UpdaterServiceSetting']
            else:
                install_automatically = 1
    else:
        try:
            install_automatically = settings['UpdaterServiceSetting']['Value']
        #because, for some godforsaken reason (we only write if it is not the default), 
        #we fail to write it at all, rather than setting the value
        except KeyError:
            install_automatically = 1
    
    #use default chunk size if none is given, set UpdaterWillingToTest to None if not given
    #this is to prevent key errors on accessing keys that may or may not exist depending on cli options given
    chunk_size = 1024
    UpdaterWillingToTest = None
    if cli_overrides is not None: 
        if 'set' in cli_overrides.keys():
            if 'UpdaterMaximumBandwidth' in cli_overrides['set'].keys():    
                chunk_size = cli_overrides['set']['UpdaterMaximumBandwidth']
            if 'UpdaterWillingToTest' in cli_overrides['set'].keys():
                UpdaterWillingToTest = cli_overrides['set']['UpdaterWillingToTest']

    #get channel and version
    try:
        summary_dict = get_summary(platform_key)
        #we send the override to the VVM, but retain the summary.json version for in_place computations
        channel_override_summary = deepcopy(summary_dict)        
        if cli_overrides is not None:
            if 'channel' in cli_overrides.keys() and channel_override_summary['Channel'] is not None:
                channel_override_summary['Channel'] = cli_overrides['channel']
    except Exception as e:
        log.debug("Update manager exited with (Success = %s, Stage = %s)" % (False, 'setup'))
        log.warning("Could not obtain channel and version.\n%r" % e)
        return (False, 'setup', None)        

    #323: On launch, the Viewer Manager should query the Viewer Version Manager update api.
    if cli_overrides is not None:
        if 'update-service' in cli_overrides.keys():
            UpdaterServiceURL = cli_overrides['update-service']
        else:
            #tells query_vvm to use the default
            UpdaterServiceURL = None
    else:
        UpdaterServiceURL = None

    result_data = query_vvm(platform_key=platform_key,
                            settings=settings,
                            summary_dict=channel_override_summary,
                            UpdaterServiceURL=UpdaterServiceURL,
                            UpdaterWillingToTest=UpdaterWillingToTest)

    #nothing to do or error
    if not result_data:
        log.info("No update.")
        log.debug("Update manager exited with (Success = %s, Stage = %s, Update Required = %s)" % (True, None, None))
        #clean up any previous download dir on windows, see apply_update.apply_update()
        try:
            if platform_key == 'win':
                past_download_dir = make_download_dir(parent_dir, channel_override_summary['Version'])
                #call make to convert our version into a previous download dir path
                #call check to see if the winstall file is there
                installed = check_for_completed_download(past_download_dir)
                log.debug("Checked for previous Windows install in %s with result %s." % (past_download_dir, installed))
                if installed == 'winstall':
                    shutil.rmtree(past_download_dir)
        except Exception as e:
            #cleanup is best effort
            log.error("Caught exception cleaning up Windows download dir %r" % e)
            pass
        return (True, None, None)

    #get download directory, if there are perm issues or similar problems, give up
    try:
        download_dir = make_download_dir(parent_dir, result_data['version'])
    except Exception as e:
        log.error("Caught exception making download dir %r" % e)
        log.debug("Update manager exited with (Success = %s, Stage = %s)" % (False, 'setup'))
        return (False, 'setup', None)
    
    #if the channel name of the response is the same as the channel we are launched from, the update is "in place"
    #and launcher will launch the viewer in this install location.  Otherwise, it will launch the Launcher from 
    #the new location and kill itself.
    in_place = (summary_dict['Channel'] == result_data['channel'])
    
    #determine if we've tried this download before
    downloaded = check_for_completed_download(download_dir, result_data['size'])

    #323: If the response indicates that there is a required update: 
    if result_data['required'] or ((not result_data['required']) and (install_automatically == 1)):
        log.info("Found required update.")
        #323: Check for a completed download of the required update; if found, display an alert, install the required update, and launch the newly installed viewer.
        #323: If [optional download and] Install Automatically: display an alert, install the update and launch updated viewer.
        return download_and_install(downloaded = downloaded, url = result_data['url'], version = result_data['version'], download_dir = download_dir, 
                        hash = result_data['hash'], size = result_data['size'], platform_key = platform_key, in_place = in_place, chunk_size = chunk_size)
    else:
        #323: If the update response indicates that there is an optional update: 
        #323: Check to see if the optional update has already been downloaded.
        #323: If a complete download of that update is found, check the update preference: 
        #note: automatic install handled above as the steps are the same as required upgrades
        #323: If Install Manually: display a message with the update information and ask the user whether or not to install the update with three choices:
        #323: Skip this update: create a marker that subsequent launches should not prompt for this update as long as it is optional, 
        #     but leave the download in place so that if it becomes required it will be there.
        #323: Install next time: create a marker that skips the prompt and installs on the next launch
        #323: Install and launch now: do it.
        log.info("Found optional update. Download directory is: " + download_dir)
        choice = -1
        if downloaded is None:        
            #multithread a download           
            try:
                os.makedirs(download_dir)
            except OSError as err:
                if err.errno == errno.EEXIST and os.path.isdir(download_dir):
                    pass
                else:
                    raise
                
            log.info("Found optional update. Downloading in background to: " + download_dir)
            result = download(url = result_data['url'], version = result_data['version'], download_dir = download_dir, 
                              hash = result_data['hash'], size = result_data['size'], background = True)
            log.debug("Update manager exited with (Success = %s, Stage = %s, Result = %s)" 
                % (True, 'background download', result))   
            return (True, 'background', result)                 
        elif downloaded == 'done' or downloaded == 'next':
            log.info("Found previously downloaded update in: " + download_dir)
            skip_frame = InstallerUserMessage.InstallerUserMessage(title = "Second Life Installer", icon_name="head-sl-logo.gif")
            skip_frame.trinary_choice_link_message(message = "Optional Update %s ready to install. Install this version?\nClick here for Release Notes" % summary_dict['Version'], 
                url = str(result_data['more_info']), one = "Yes", two = "No", three = "Not Now")
            skip_me = skip_frame.choice3.get()
            if skip_me == 1:
                result = install(platform_key = platform_key, download_dir = download_dir, in_place = in_place, downloaded = downloaded)
                #overwrite path with in place signal value
                if in_place:
                    result = True
                log.debug("Update manager exited with (Success = %s, Install Type = %s, Install Type Decision = %s)" % (True, 'in place', str(result)))
                return (True, 'in place', result)
            elif skip_me == 2:                  
                tempfile.mkstemp(suffix=".skip", dir=download_dir)
                log.debug("Update manager exited with (Success = %s, Install Type = %s, Install Type Decision = %s)" % (True, 'in place', True))
                return (True, 'in place', True)
            else:
                tempfile.mkstemp(suffix=".next", dir=download_dir)
                log.debug("Update manager exited with (Success = %s, Install Type = %s, Install Type Decision = %s)" % (True, 'in place', True))
                return (True, 'in place', True)                
        elif downloaded == 'skip':
            log.info("Skipping this update per previous choice.  Delete the .skip file in " + download_dir + " to change this.")
            return (True, 'skip', True)        
        else:
            #shouldn't be here
            log.warning("Found nonempty download dir but no flag file. Check returned: %r" % downloaded)
            return (True, 'skip', True)


if __name__ == '__main__':
    #this is mostly for testing on Windows, emulating exe enviroment with $python scriptname
    if 'ython' in sys.executable:
        sys.executable =  os.path.abspath(sys.argv[0])
    #there is no argument parsing or other main() work to be done
    # Initialize the python logging system to SL Logging format and destination
    log = SL_Logging.getLogger('SL_Updater')
    update_manager()
