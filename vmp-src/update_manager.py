#!/usr/bin/env python

"""\
$LicenseInfo:firstyear=2017&license=viewerlgpl$
Second Life Viewer Source Code
Copyright (C) 2017, Linden Research, Inc.

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
from sets import Set
from vmp_util import Application, BuildData, SL_Logging, subprocess_args, skip_settings, write_settings
from llbase import llsd
from llbase import llrest

import apply_update
import download_update
import errno
import fnmatch
import hashlib
import InstallerUserMessage
import itertools
import json
import os
import os.path
import re
import platform
import shutil
import subprocess
import sys
import tempfile
import thread
import time
#for the quote method
import urllib
#for the disable_warnings method 
import urllib3
import warnings


#module globals
download_process = None
#See getBitness().  This is an exclusion list created by experimental techniques
#and research that is extrinsic to VMP.  64bit viewer does not run on these.
#
#Also, only some HDs are bad, unfortunately, some of the bad ones have no model number
#so instead of 'Intel(R) HD Graphics 530' we just get 'Intel(R) HD Graphics'
#hence the strange equality test for 'Graphics' when we pop the last word off the string.
mHD_GRAPHICS_LIST = ['Graphics', '2000', '2500', '3000', '4000']

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
    try:
        return version.replace('.', '_')
    except AttributeError:
        # if 'version' isn't a string, just return it
        return version

def make_download_dir(base_dir, new_version):
    #make a canonical download dir if it does not already exist
    #format: ../user_settings/downloads/1.2.3.456789
    #we do this so that multiple viewers on the same host can update separately
    #this also functions as a getter 
    try:
        download_dir = os.path.join(base_dir, "downloads", new_version)
        os.makedirs(download_dir)
    except OSError as hell:
        #Directory already exists, that's okay.  Other OSErrors are not okay.
        if not (hell.errno == errno.EEXIST and os.path.isdir(download_dir)):
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

def get_settings(parent_dir, other_file=None):
    #return the settings file parsed into a dict
    #defaults to settings.xml, use other_file for some other xml file in user_settings
    settings={}
    log=SL_Logging.getLogger('get_settings')
    #this happens when the path to settings file happens on the command line
    #we get a full path and don't need to munge it
    if os.path.isfile(parent_dir):
        settings_file = parent_dir
    else:
        settings_file = os.path.abspath(os.path.join(parent_dir,'user_settings',
                                                     other_file or 'settings.xml'))

    try:
        settings = llsd.parse((open(settings_file)).read())
    except llsd.LLSDParseError as lpe:
        log.warning("Could not parse settings file %s: %s" % (settings_file, lpe))
    except Exception as e:
        log.warning("Could not read settings file %s: %s" % (settings_file, e))
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
                                                          log_stream=SL_Logging.stream_from_process(hostid_cmd)
                                                          )).rstrip()
        log.debug("result of subprocess call to get linux MUUID: %r" % muuid)
    elif (platform_key == 'mac'):
        #this is absurdly baroque
        #/usr/sbin/system_profiler SPHardwareDataType | fgrep 'Serial' | awk '{print $NF}'
        #also note that this causes spurious messages about X86PlatformPlugin in the log from stderr
        # ignoring per https://tickets.puppetlabs.com/browse/FACT-724, stdout is correct, stderr is noise
        profiler_cmd=["/usr/sbin/system_profiler", "SPHardwareDataType"]
        muuid = subprocess.check_output(profiler_cmd,
                                        **subprocess_args(include_stdout=False,
                                                          log_stream=SL_Logging.stream_from_process(profiler_cmd)))
        #findall[0] does the grep for the value we are looking for: "Serial Number (system): XXXXXXXX"
        #split(:)[1] gets us the XXXXXXX part
        #lstrip shaves off the leading space that was after the colon
        muuid = re.split(":", re.findall('Serial Number \(system\): \S*', muuid)[0])[1].lstrip()
        log.debug("result of subprocess call to get mac MUUID: %r" % muuid)
    elif (platform_key == 'win'):
        # wmic csproduct get UUID | grep -v UUID
        wmic_cmd=['wmic','csproduct','get','UUID']
        muuid = subprocess.check_output(wmic_cmd,
                                        **subprocess_args(include_stdout=False,
                                                          log_stream=SL_Logging.stream_from_process(wmic_cmd)))
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

def getBitness(platform_key = None, settings=None):
    log=SL_Logging.getLogger('getBitness')
    log.debug("getBitness called with: %r and %r" % (platform_key, settings))
    if platform_key in ['lnx', 'mac']:
        return 64
    if 'PROGRAMFILES(X86)' not in os.environ:
        return 32
    else:
        #see MAINT-6832, MAINT-7571 and IQA-4130
        wmic_cmd=['wmic','path','Win32_VideoController','get','NAME']
        wmic_graphics = subprocess.check_output(wmic_cmd,
                                                **subprocess_args(include_stdout=False,
                                                                  log_stream=SL_Logging.stream_from_process(wmic_cmd)))
        log.debug("result of subprocess call to get wmic graphics card info: %r" % wmic_graphics)
        wmic_graphics = wmic_graphics.rstrip()
        wmic_list = re.split('\r', wmic_graphics)
        good = True
        # the first line of the response is always the string literal 'Name' and then a ''  Discard them.
        wmic_list.pop(0)
        wmic_list.pop(0)

        for line in wmic_list:
            log.debug("Current WMIC list entry: %r"% line)
            #Any card other than the bad ones will work
            if line.find("Intel(R) HD Graphics") > -1:
                word = line.split().pop()
                log.debug("Current word: %r"% word)
                if word in mHD_GRAPHICS_LIST:
                    log.debug("Found a bad card")
                    good = False
            # '' and '\n' occurs as a split artifact, ignore them
            elif (line != '' and line != '\n'):
                #some other card, anything is good.
                good = True
                log.debug("Found a good card")
                #there's no order guarantee from wmic, this is to prevent an
                #HD card discovered after a good card from overwriting the state variable
                #by specification, a machine is bad iff ALL of the cards on the machine are bad ones
                break
            
        if not good:
            log.debug("Graphics card determined to be bad.")
            addr = 32
            if 'ForceAddressSize' in settings.keys():
                addr = settings['ForceAddressSize']
                log.debug("ForceAddressSize parameter found with argument: %r" % addr)
            if addr == '64':
                log.info("Turning off benchmarking in viewer startup.")
                #write to settings file, see MAINT-7571
                settings_path = os.path.join(Application.userpath(),'user_settings', 'settings.xml')
                settings = get_settings(settings_path)
                log.debug("Settings before skip benchmark modification: %r" % settings)
                
                #overwrite settings files          
                if settings is not None:
                    if 'SkipBenchmark' in settings.keys():
                        #don't care what it was, kill it and then write what we want
                        settings.pop('SkipBenchmark')
                    settings.append(skip_settings)
                else:
                    #no settings file, just make one.  llsd printer invoked via write_settings handles the enclosing llsd/xml
                    settings = skip_settings
                try:
                    log.debug("Settings just before skip benchmark writing: %r" % settings)
                    write_settings(settings_object=settings, settings_path=settings_path)
                except Exception, e:
                    log.error("Failed to write to settings file: %r" % e)
                    return 32
            else:
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

def query_vvm(platform_key = None, settings = None,
              UpdaterServiceURL = None, UpdaterWillingToTest = None):
    result_data = None

    VVM_platform = platform_key
    log=SL_Logging.getLogger('query_vvm')

    if not UpdaterServiceURL:
        UpdaterServiceURL=os.getenv('SL_UPDATE_SERVICE',
            BuildData.get('Update Service',
                          'https://update.secondlife.com/update'))

    # To disambiguate, we have two sources of platform here
    #   - platform_key is our platform name for the computer we are running on
    #   - BuildData.get('Platform') is the platform for which we were packaged
    # These are not always the same, in particular, for the first download of a VMP windows viewer which defaults to 64 bit
    bitness = getBitness(platform_key, settings)
    log.debug("Bitness determined to be %r" % bitness)
    
    try:
        if not isViewerMachineBitMatched(BuildData.get('platform'), platform_key, bitness):
            #there are two cases:
            # the expected case where we downloaded a 64 bit viewer to a 32 bit machine on spec
            # the unexpected case where someone was running a 32 bit viewer on a 32 bit Windows box and upgraded their Windows to 64 bit
            #either way, the Windows bitness is the right bitness
            if bitness == 32:
                VVM_platform = 'win32'
    except Exception as e:
        log.warning("Could not parse viewer bitness from build_data.json %r" % e)
        #At these point, we have no idea what is really going on.  Since 32 installs on 64 and not vice-versa, fall back to safety
        VVM_platform = 'win32'        

    # URI template /update/v1.2/channelname/version/platformkey/platformversion/willing-to-test/uniqueid
    # https://wiki.lindenlab.com/wiki/Viewer_Version_Manager_REST_API#Viewer_Update_Query
    # For valid hosts, see https://wiki.lindenlab.com/wiki/Update_Service#Clusters
    channelname = BuildData.get('Channel')
    version = BuildData.get('Version')
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
    if UpdaterWillingToTest == 'testok':
        test_ok = 'testok'
    elif re.search('^%s Test' % Application.name(), channelname) is not None:
        test_ok = 'testno'
    else:
        test_ok = settings.get('test', {}).get('Value', 'testok')
            
    #suppress warning we get in dev env for altname cert 
    if UpdaterServiceURL != 'https://update.secondlife.com/update':
        warnings.simplefilter('ignore', urllib3.exceptions.SecurityWarning)
    
    #channelname is a list because although it is only one string, it is a kind of argument and viewer args can take multiple keywords.
    log.info("Requesting update for channel '%s' version %s platform %s platform version %s allow_test %s id %s" %
             (str(channelname), version, VVM_platform, platform_version, test_ok, UUID))
    update_urlpath =  urllib.quote('/'.join(['v1.2', str(channelname), version, VVM_platform, platform_version, test_ok, UUID]))
    log.debug("Sending query to VVM: query %s/%s" % (UpdaterServiceURL, update_urlpath))
    VVMService = llrest.SimpleRESTService(name='VVM', baseurl=UpdaterServiceURL)
    
    try:
        result_data = VVMService.get(update_urlpath)
        log.info("received result from VVM: %r" % result_data)
    except llrest.RESTError as res:
        if res.status == 404: # 404 is how the Viewer Version Manager indicates that the channel is unmanaged
            log.info("Update service returned 'not found'; normally this means the channel is unmanaged (and allowed)")
        else:
            log.warning("Update service %s/%s failed: %s" % (UpdaterServiceURL, update_urlpath, res))
    #keep a copy for logging later
    raw_result_data = result_data
            
    #As of VVM v1.2, the result_data object is now a bit more complicated.  The general information
    #such as required, channel and so on are still at the top level, but url, hash and size are now returned 
    #for all platforms at once, keyed by platform key.  So, the mac download url is result_data['platforms']['mac']['url']
    #and similarly for the other values and platforms.  Platform key is still one of {lnx,mac,win,win32}
    #Before this, the result_data had these three at the top level, which is what the caller expects.  We
    #continue this contract by selecting the right values here where we know the correct bitness and this means
    #the rest of the code does not need to be changed.
    if result_data is not None:
        #no update or VVM doesn't know about this version.
        #we only do an "cross-platform" update in the case where we have downloaded a win64 viewer on initial install
        #to a win32 bit machine or when a 64 bit host has a win32 viewer.
        #
        #In these cases, we return a result that effectively says "required upgrade to win/win32".
        #otherwise result == current means no update (and likely, a test viewer)
        if result_data['version'] == version:
            if VVM_platform == BuildData.get('platform'):
                log.info("We have version %s for %s, which is correct" % (version, VVM_platform))
                return None # we have what we should have
            else:
                #Don't care what the VVM says, sideways upgrades are ALWAYS mandatory
                result_data['required'] = True        

        try:
            result_data.update(result_data['platforms'][VVM_platform]) # promote the target platform results 
            result_data['VVM_platform'] = VVM_platform
        except KeyError as ke:
            #this means we got a malformed response; either 'platforms' isn't in the results, or our platform is missing
            if 'platforms' in result_data:
                log.warning("Unexpected response - no data for platform '%s': %r" % (VVM_platform, raw_result_data))
            else:
                log.error("Received malformed results from vvm: %r" % result_data)
            log.error("Error from reading VVM response: %r" % ke)
            result_data = None
        else:
            #get() sets missing key results to None.  If we are missing any data, set the whole thing to None
            if not ('hash' in result_data and 'size' in result_data and 'url' in result_data):
                log.error("No update because response is missing url, size, or hash: %r" % raw_result_data)
                result_data = None
                
    #failsafe to prevent 64 bit viewer crashing on startup on a 32 bit host.
    if VVM_platform == 'win32' and result_data is None and BuildData.get('Platform') != 'win32':
        log.error("Could not obtain 32 bit viewer information.  Response from VVM was %r " % raw_result_data)
        after_frame("Failed to obtain a 32 bit viewer for your system.  Please download a viewer from http://secondlife.com/support/downloads/")
        #we're toast.  We don't have a 32 bit viewer to update to and we can't launch a 64 bit viewer on a 32 bit host
        #better to die gracefully than horribly
        sys.exit(1) 
                
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
    if Application.platform_key() == 'win':
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
                downloader_cmd = [path_to_downloader,
                                  "--url", url,
                                  "--dir", download_dir, 
                                  "--size", str(size),
                                  "--chunk_size", str(chunk_size)]
                download_process = subprocess.Popen(downloader_cmd,
                                                    **subprocess_args(include_stdout=True,
                                                                      log_stream=SL_Logging.stream_from_process(downloader_cmd, streams="stdout and stderr")))
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
            return (True, 'in place', None)
    else:
        #propagate failure
        return (False, 'apply', version)    

def update_manager(*args, **kwds):
    """wrapper that logs entry/exit"""
    log = SL_Logging.getLogger('update_manager')
    log.debug("update_manager(%s)" %
              ", ".join(itertools.chain((repr(arg) for arg in args),
                                        "%s=%r" % item for item in kwds.items())))
    result = _update_manager(*args, **kwds)
    log.debug("update_manager() => %r" % result)
    return result

def _update_manager(cli_overrides = {}):
    log = SL_Logging.getLogger('update_manager')

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
    platform_key = Application.platform_key()
    parent_dir = Application.userpath()

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
                return (False, 'setup', None)
    except (AttributeError, ImportError):
        #Windows throws AttributeError on getuid() and ImportError on pwd
        #Just ignore it and consider the ID check as passed.
        pass

    settings = get_settings(cli_overrides.get('settings') or parent_dir)

    #323: If a complete download of that update is found, check the update preference:
    #settings['UpdaterServiceSetting'] = 0 is manual install
    #
    # <key>UpdaterServiceSetting</key>
    #     <map>
    # <key>Comment</key>
    #     <string>Configure updater service.</string>
    # <key>Type</key>
    #     <string>U32</string>
    # <key>Value</key>
    #     <string>0</string>
    # </map>

    # If cli_overrides['set']['UpdaterServiceSetting'], use that;
    # else if settings['UpdaterServiceSetting']['Value'], use that;
    # if none of the above, default to True.
    install_automatically = cli_overrides.get('set', {}).get('UpdaterServiceSetting',
        settings.get('UpdaterServiceSetting', {}).get('Value', True))
    
    #use default chunk size if none is given, set UpdaterWillingToTest to None if not given
    #this is to prevent key errors on accessing keys that may or may not exist depending on cli options given
    cli_set = cli_overrides.get('set')
    # "chunk_size" ? "UpdaterMaximumBandwidth" ? Are these the same thing?
    chunk_size = cli_set.get('UpdaterMaximumBandwidth', 1024)
    UpdaterWillingToTest = cli_set.get('UpdaterWillingToTest')
    UpdaterServiceURL = cli_set.get('UpdaterServiceURL')

    # get channel and version
    default_channel = BuildData.get('Channel')
    # we send the override to the VVM, but retain the default_channel version for in_place computations
    channel = cli_overrides.get('channel') 
    if channel not in (None, default_channel):
        log.info("Overriding channel '%s' with '%s' from command line" %
                 (default_channel, channel))
        BuildData.override('Channel', channel)
    
    settings['ForceAddressSize'] = cli_overrides.get('forceaddresssize')
        
    log.debug("Pre query settings: %r" % settings)

    #323: On launch, the Viewer Manager should query the Viewer Version Manager update api.
    result_data = query_vvm(platform_key=platform_key,
                            settings=settings,
                            UpdaterServiceURL=UpdaterServiceURL,
                            UpdaterWillingToTest=UpdaterWillingToTest)
    log.debug("result_data received from query_VVM: %r" % result_data)

    #nothing to do or error
    if not result_data:
        log.info("No update.")
        #clean up any previous download dir on windows, see apply_update.apply_update()
        try:
            if platform_key == 'win':
                past_download_dir = make_download_dir(Application.userpath(), BuildData.get('Version'))
                #call make to convert our version into a previous download dir path
                #call check to see if the winstall file is there
                installed = check_for_completed_download(past_download_dir)
                log.debug("Checked for previous Windows install in %s with result %s." % (past_download_dir, installed))
                if installed == 'winstall':
                    log.info("Cleaning up past download dirctory '%s'" % past_download_dir)
                    shutil.rmtree(past_download_dir)
        except Exception as e:
            #cleanup is best effort
            log.error("Caught exception cleaning up download dir '%r'; skipping" % e)
            pass
        return (True, None, None)

    #Don't do sideways upgrades more than once.  See MAINT-7513
    #Get version and platform from build_data (source of truth for local install) and VVM query result
    #and if they pairwise equal return no update, e.g., we are running a 32 bit viewer on a 32 bit host.
    if BuildData.get('Platform', None) == result_data['VVM_platform'] and BuildData.get('Version', None) == result_data['version']:
        #no sideways upgrade required
        return (True, None, None)
    
    #get download directory, if there are perm issues or similar problems, give up
    try:
        download_dir = make_download_dir(Application.userpath(), result_data['version'])
    except Exception as e:
        log.error("Caught exception making download dir %r" % e)
        return (False, 'setup', None)
    
    #if the channel name of the response is the same as the channel we are launched from, the update is "in place"
    #and launcher will launch the viewer in this install location.  Otherwise, it will launch the Launcher from 
    #the new location and kill itself.
    in_place = (default_channel == result_data['channel'])
    log.debug("In place determination: in place %r build_data %r result_data %r" % (in_place, BuildData.get('Channel'), result_data['channel']))
    
    #determine if we've tried this download before
    downloaded = check_for_completed_download(download_dir, result_data['size'])

    #323: If the response indicates that there is a required update: 
    if result_data['required'] or ((not result_data['required']) and (install_automatically == 1)):
        log.info("Required update to version %s" % result_data['version'])
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
            # start a background download           
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
            return (True, 'background', result)                 
        elif downloaded == 'done' or downloaded == 'next':
            log.info("Found previously downloaded update in: " + download_dir)
            skip_frame = InstallerUserMessage.InstallerUserMessage(title = BuildData.get('Channel Base')+" Installer", icon_name="head-sl-logo.gif")
            skip_frame.trinary_choice_link_message(message = "Optional Update %s ready to install. Install this version?\nSee Release Notes" % result_data['version'], 
                url = str(result_data['more_info']), one = "Yes", two = "No", three = "Not Now")
            skip_me = skip_frame.choice3.get()
            if skip_me == 1:
                result = install(platform_key = platform_key, download_dir = download_dir, in_place = in_place, downloaded = downloaded)
                #overwrite path with in place signal value
                if in_place:
                    result = True
                return (True, 'in place', result)
            elif skip_me == 2:                  
                tempfile.mkstemp(suffix=".skip", dir=download_dir)
                return (True, 'in place', True)
            else:
                tempfile.mkstemp(suffix=".next", dir=download_dir)
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
    try:
        update_manager()
    except Exception:
        log.exception("Unhandled exception")
