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
from logging import DEBUG
from vmp_util import Application, BuildData, SL_Logging, subprocess_args, put_marker_file
from llbase import llsd
from llbase import llrest

import apply_update
import download_update
import errno
import glob
import hashlib
import InstallerUserMessage
import itertools
import json
import os
import os.path
from pprint import pformat
import re
import platform
import shutil
import subprocess
import sys
import tempfile
# specifically import the sleep() function for testability
from time import sleep
#for the quote method
import urllib
#for the disable_warnings method 
import urllib3
import warnings


class UpdateError(Exception):
    pass

class UpdateErrorIn(UpdateError):
    def __init__(self, state):
        super(UpdateErrorIn, self).__init__(
            'Update failed in the %s process.  Please check logs.' % state)


#module globals
download_process = None
#See getBitness().  This is an exclusion list created by experimental techniques
#and research that is extrinsic to VMP.  64bit viewer does not run on these.
#
#Also, only some HDs are bad, unfortunately, some of the bad ones have no model number
#so instead of 'Intel(R) HD Graphics 530' we just get 'Intel(R) HD Graphics'
#hence the strange equality test for 'Graphics' when we pop the last word off the string.
UnsupportedHD_GRAPHICS_LIST = ['Graphics', '2000', '2500', '3000', '4000']

#this is to support pyinstaller, which uses sys._MEIPASS to point to the location
#the bootloader unpacked the bundle to.  If the getattr returns false, we are in a 
#normal Python environment.
if getattr(sys, 'frozen', False):
    __file__ = sys._MEIPASS

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

def make_download_dir(new_version):
    #make a canonical download dir if it does not already exist
    #format: ../user_settings/downloads/1.2.3.456789
    #we do this so that multiple viewers on the same host can update separately
    #this also functions as a getter 
    try:
        download_dir = os.path.join(Application.userpath(), "downloads", new_version)
        os.makedirs(download_dir)
    except OSError as hell:
        #Directory already exists, that's okay.  Other OSErrors are not okay.
        if not (hell.errno == errno.EEXIST and os.path.isdir(download_dir)):
            raise
    return download_dir

def check_for_completed_download(download_dir, expected_size = 0):
    """
    Return:
    'winstall' if we previously launched a Windows NSIS installer from there; else
    'skip' if the user asked never to install this version; else
    'next' if the user asked to defer installation until next run; else
    'done' if we finished downloading a new installer; else
    None if the directory doesn't even exist.
    """
    log=SL_Logging.getLogger('check_for_completed_download')
    #there will be two files on completion, the download and a marker file called "".done""
    #for optional upgrades, there may also be a .skip file to skip this particular upgrade 
    #or a next file which defers the choice to the next startup.
    if not os.path.exists(download_dir):
        return None
    # Construct a dict whose keys are filename extensions and values are the filenames.
    files_by_ext = { os.path.splitext(f)[1]: f
                     for f in os.listdir(download_dir) }
    #Done has the least priority,
    #next is second and skip is highest.  That is, if the resident said skip, never ask again.  
    #Recall that this download_dir is specific to this viewer version.
    #List marker-file extensions in the order in which we care about them.
    priority = ['.winstall', '.skip', '.next', '.done']

    # return the highest-priority marker we have
    for ext in priority:
        if ext in files_by_ext:
            log.debug('download_dir %s has %s marker', download_dir, ext)
            return ext.lstrip('.')

    # no markers: we found some sort of partial remnants of a download
    installer = apply_update.get_filename(download_dir)
    if not installer:
        log.warning("no installer in download_dir %s, deleting", download_dir)
        #cleanup the mess, start over next time
        shutil.rmtree(download_dir)
        return None

    #the theory of operation is that if the file hasn't changed in ten seconds
    #there is no download in progress
    samples = []
    for x in sleep_between(
        range(2),                       # returned items
        'download_dir %s has partial installer %s (expecting %s), sleeping' %
        (download_dir, installer, expected_size),
        10):                            # sleep seconds
        # See sleep_between() below. The idea is to execute this block once,
        # maybe twice -- but we sleep() only after the *first* iteration, not
        # the second.
        # Are we there yet?
        samples.append(os.path.getsize(installer))
        # If, on either check, the file reached the expected size, we're good.
        if samples[-1] == expected_size:
            log.debug('%d: download_dir %s has installer %s of expected size %s, done',
                      x+1, download_dir, installer, expected_size)
            # Place a marker for future reference.
            put_marker_file(download_dir, ".done")
            return 'done'

    # If we get here at all, there are exactly two samples. If the second is
    # bigger than the first, there's a download in progress elsewhere.
    if samples[1] > samples[0]:
        #this is a protocol hack.  The caller will see this and interpret the download
        #in progress as an optional update to be ignored.  Later, when done, a later launch
        #instance will see the completed download and act accordingly.
        log.debug('download_dir %s has installer %s being downloaded, fake skip',
                  download_dir, installer)
        return 'skip'

    # No markers, unfinished download, not currently downloading
    log.debug('download_dir %s has partial installer %s (%s, expecting %s), deleting',
              download_dir, installer, second_sample, expected_size)
    shutil.rmtree(download_dir)
    return None

def sleep_between(iterable, message, duration):
    """
    Yield items from the passed iterable, logging (and sleeping) in between
    items. This is a bit like str.join() in that the sleep only happens
    *between* items -- neither before the first nor after the last. In other
    words:

    0 items: no sleep
    1 item:  no sleep
    2 items: 1 sleep
    etc.

    If your 'message' contains '{n}', it is replaced with the count of items
    that have already been yielded -- thus, '1' for the first log message, '2'
    for the second and so forth.

    If your 'message' contains '{t}', it is replaced with the passed duration.
    """
    log = SL_Logging.getLogger('sleep_between')
    it = iter(iterable)
    # Yield the first item immediately.
    # Of course let StopIteration propagate for the empty case.
    yield next(it)
    # loop over the rest of the items
    for n, item in enumerate(it):
        log.info(message.format(n=n+1, t=duration))
        sleep(duration)
        yield item

def get_settings(settings_file):
    #return the settings file parsed into a dict
    settings={}
    log=SL_Logging.getLogger('get_settings')

    try:
        settings = llsd.parse(open(settings_file).read())
    except llsd.LLSDParseError as lpe:
        log.warning("Could not parse settings file %s: %s" % (os.path.abspath(settings_file), lpe))
    except Exception as e:
        log.warning("Could not read settings file %s: %s" % (os.path.abspath(settings_file), e))
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
        muuid = wmic('csproduct','get','UUID')
        #outputs in two rows:
        #UUID
        #XXXXXXX-XXXX...
        muuid = muuid.splitlines()[1].rstrip()
        log.debug("result of subprocess call to get win MUUID: %r" % muuid)
            
    if muuid is not None:
        hash = hashlib.md5(muuid).hexdigest()
    else:
        #fake it
        log.info("Unable to get system unique id; constructing a dummy")
        hash = hashlib.md5(str(uuid.uuid1())).hexdigest()
    return hash

def getBitness(platform_key):
    """Return the maximum possible address size for this system"""
    log=SL_Logging.getLogger('getBitness')
    bits = 0
    # log.debug("getBitness called with: %r and %r" % (platform_key, settings))
    if platform_key in ['lnx', 'mac']:
        bits = 64
    # always Windows from here down...
    elif 'PROGRAMFILES(X86)' not in os.environ:
        bits = 32
    else:
        bits = 64
    log.debug("returning %d bit" % bits)
    return bits

def wmic(*args):
    """
    Run the Windows wmic command with specified arguments, returning its
    stdout (or raising an exception).

    Breaking this out as a separate function improves testability.
    """
    log = SL_Logging.getLogger('wmic')
    wmic_cmd = ("wmic",) + args
    try:
        return subprocess.check_output(
            wmic_cmd,
            **subprocess_args(include_stdout=False,
                              log_stream=SL_Logging.stream_from_process(wmic_cmd)))
    except OSError as err:
        if err.errno == errno.ENOENT:
            log.error("No wmic command found - bad Windows install?")
        raise

def query_vvm(platform_key = None, settings = {},
              UpdaterServiceURL = None, UpdaterWillingToTest = None):
    """
    Ask the viewer version manager what builds are available for me
    given my platform and version.
    Returns a map of all responses.
    """
    result_data = None

    log=SL_Logging.getLogger('query_vvm')

    # URI template /update/v1.2/channelname/version/platform/platformversion/willing-to-test/uniqueid
    # https://lindenlab.atlassian.net/wiki/spaces/SLT/pages/71106564/Viewer+Version+Manager+REST+API
    # See https://lindenlab.atlassian.net/wiki/spaces/SLT/pages/466081/Viewer+Version+Manager+in+AWS

    VVM_platform = platform_key

    if not UpdaterServiceURL:
        UpdaterServiceURL=os.getenv('SL_UPDATE_SERVICE',
            BuildData.get('Update Service',
                          'https://update.secondlife.com/update'))

    bitness = getBitness(platform_key)

    # Ask the VVM with the most specific form of our platform (including bitness)
    # so that if it can be configured with more specific rules
    VVM_platform = "%s%d" % (platform_key, bitness)

    channelname = BuildData.get('Channel')
    version = BuildData.get('Version')
    # we need to use the dotted versions of the platform versions in order to be compatible with VVM rules and arithmetic
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
        # if running a Second Life Test viewer, don't accept other test viewers
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
    debug_param= {'explain': 1} if log.isEnabledFor(DEBUG) else {}; # if debugging, ask the VVM to say how it got the response 
    log.debug("Sending query to VVM: query %s/%s%s" % (UpdaterServiceURL, update_urlpath, (" with explain requested" if debug_param else "")))
    VVMService = llrest.SimpleRESTService(name='VVM', baseurl=UpdaterServiceURL)
    
    try:
        result_data = VVMService.get(update_urlpath, params=debug_param)
        log.debug("received result from VVM: %r" % result_data)
        result_data.pop('explain', None) # logging the explanation above is enough, not needed elsewhere
    except llrest.RESTError as res:
        if res.status == 404: # 404 is how the Viewer Version Manager indicates that the channel is unmanaged
            log.info("Update service returned 'not found'; normally this means the channel is unmanaged (and allowed)")
        else:
            log.warning("Update service %s/%s failed: %s" % (UpdaterServiceURL, update_urlpath, res))
        result_data = None

    return result_data

def onWindows10orHigher():
    if platform.system() != 'Windows':
        return False
    log = SL_Logging.getLogger('onWindows10orHigher')
    windowsVersion = platform.win32_ver()[1]
    majorVersion=int(windowsVersion.split('.')[0])
    log.debug("Windows version %s is %s10 or greater" % (windowsVersion, ("not " if majorVersion < 10 else "")))
    return majorVersion >= 10

class Windows10Video(object):
    hasOnlyUnsupported = None # so that we only call wmic once

    @staticmethod
    def isUnsupported():
        if Windows10Video.hasOnlyUnsupported is None:
            log = SL_Logging.getLogger('windows_video')

            # There are video cards that are not supported for the 64bit build on Windows 10,
            # so find out what the video controller is
            wmic_graphics = wmic('path','Win32_VideoController','get','NAME')
            log.debug("wmic graphics card info: %r" % wmic_graphics)
            # first rstrip() every line, then discard any that are completely blank
            # the first line of the response is always the string literal 'Name'
            wmic_list = [line for line in
                             (ln.rstrip() for ln in wmic_graphics.splitlines())
                             if line][1:]
            if wmic_list:
                # The logic here is a little complicated:
                # - If there's no bad card, we're good.
                # - If there's a bad card AND some other card, still good.
                # - If the only card(s) present are bad cards, not good.
                good_cards = [line for line in wmic_list
                                  if not ("Intel(R) HD Graphics" in line and
                                              line.split()[-1] in UnsupportedHD_GRAPHICS_LIST)]
                # There's no order guarantee from wmic, this is to prevent an
                # HD card discovered after a good card from overwriting the state variable
                # by specification, a machine is bad iff ALL of the cards on the machine are bad ones
                if good_cards:
                    Windows10Video.hasOnlyUnsupported = False
                    log.debug("Found at least one good graphics card: '%s'", "', '".join(good_cards))
                    # so we can leave the target win64
                else:
                    # all we found were cards that are not supported in the Windows 64bit build
                    Windows10Video.hasOnlyUnsupported = True
                    log.warning("Found only graphics cards not supported in Windows 10: '%s'; should switch to the 32 bit build", "', '".join(wmic_list))
            else:
                log.warning("wmic did not return any video cards")
                Windows10Video.hasOnlyUnsupported = False # we are probably hosed, but go ahead and try

        return Windows10Video.hasOnlyUnsupported

def choose_update(platform_key, settings, vvm_response):
    """
    This is where we do the hard stuff - picking which result applies to this system

    Returns a chosen result dict with keys:
       required, channel, version, url, size, hash, more_info, platform
    or, if no update is chosen, an empty dict
    """
    chosen_result = dict()
    log = SL_Logging.getLogger('choose_update')

    current_build = "%s%d" % (BuildData.get('Platform'), int(BuildData.get('Address Size')))
    target_platform = "%s%d" % (platform_key, getBitness(platform_key))
    log.debug("Current build is %s; tentative target is %s" % (current_build, target_platform))

    if platform_key == 'win':
        # for Windows, there's more to it than that....
        if current_build == 'win64' and target_platform == 'win32':
            log.info("This is a 64 bit build, but this system is 32 bit; looking for a 32 bit build")

        elif target_platform == 'win64' and onWindows10orHigher() and Windows10Video.isUnsupported():
            log.warning("Your video card(s) are not supported on Windows 10; switching you to the 32bit build, which runs in a compatibility mode that works better")
            target_platform = 'win32'

    # We could have done this check earlier, but by waiting we can make the warnings more specific
    if settings.get('ForceAddressSize',None):
        if platform_key == 'win':
            try:
                forced_bitness = int(settings['ForceAddressSize'])
                log.info("ForceAddressSize setting: %d" % forced_bitness)
                if target_platform == 'win32' and forced_bitness == 64:
                    log.warning("The ForceAddressSize setting says 64; that may not work, but trying anyway...")
                    target_platform = 'win64'
                elif target_platform == 'win64' and forced_bitness == 32:
                    log.warning("The ForceAddressSize setting says 32; your system may work with 64 - consider removing the setting")
                    target_platform = 'win32'
                else:
                    log.info("target platform is %s, ForceAddressSize is %d; no effect" % (target_platform, forced_bitness))

            except ValueError:
                log.warning("Invalid value '%s' for ForceAddressSize setting; disregarding it" % settings['ForceAddressSize'])
        else:
            log.warning('The ForceAddressSize setting is used only on Windows; ignored')

    # Ok... now we know what the target_platform is ...

    # Get all the VVM results that are not platform dependent
    for key in ['required', 'version', 'channel', 'more_info']:
        try:
            chosen_result[key] = vvm_response[key]
        except KeyError:
            log.error("Viewer Version Manager response is missing '%s'; not updating" % key)
            return dict()

    if target_platform != current_build:
        log.info("Current build platform is '%s', but we need '%s', so update is required" % (current_build, target_platform))
        chosen_result['required'] = True

    elif vvm_response['version'] == BuildData.get('Version'):
        log.info("Current version and platform matches this build; no update")
        return dict()

    # We believe we have at least an optional update, so fill in the rest of chosen_result
    # See if the VVM gave us a result for the target_platform
    target_result = vvm_response.get('platforms', {}).get(target_platform, {})
    if not target_result:
        # check to see if a result not qualified by address_size is in the results
        target_result = vvm_response.get('platforms', {}).get(platform_key, {})
        if target_result:
            log.warning("No update result found for '%s' but found '%s', so updating to that" % (target_platform, platform_key))
            target_platform = platform_key
        else:
            log.warning("No update result found for '%s' or '%s'" % (target_platform, platform_key))
            chosen_result = dict()

    # add the target we picked
    chosen_result['platform'] = target_platform
    chosen_result.update(target_result)

    return chosen_result

def download(url = None, version = None, download_dir = None, size = 0, hash = None, background = False, chunk_size = None):
    log=SL_Logging.getLogger('download')
    download_tries = 0
    download_success = False
    download_process = None
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
        #  Check for a partial update of the required update; in either event, display an alert that a download is required, initiate the download, and then install and launch
        if not background:
            log.debug("foreground downloader args: %r" % ["--url", url, "--dir", download_dir, 
                            "--size", str(size), "--chunk_size", str(chunk_size)])
            if download_tries == 0:
                InstallerUserMessage.status_message("Downloading new version " + version +
                                                    " Please wait.")
            else:
                InstallerUserMessage.status_message("Trying again to download new version " +
                                                    version + " Please wait.")
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
        message = "Failed to download new version %s from %s. Please check connectivity." % \
                  (version, url)
        log.warning(message)
        if not background:
            InstallerUserMessage.basic_message(message)
        raise UpdateError(message)
    
    #cleanup, so that we don't download twice
    for filename in glob.glob(os.path.join(download_dir, '*.next')):
        os.remove(filename)

def install(platform_key = None, download_dir = None):
    log=SL_Logging.getLogger('install')
    InstallerUserMessage.status_message("New version downloaded.\n"
                                        "Installing now, please wait.")
    version = os.path.basename(download_dir)
    try:
        next_executable = apply_update.apply_update(download_dir, platform_key)
    except apply_update.ApplyError as err:
        InstallerUserMessage.basic_message("Failed to apply " + version)
        log.warning("Failed to update viewer to " + version)
        raise UpdateError("Failed to apply version %s update: %s" %
                          (version, err))

    #windows is cleaned up on the following run, see apply_update.apply_update()
    if platform_key != 'win':
        shutil.rmtree(download_dir)
    #this is the path to the new install
    return next_executable

def update_manager(*args, **kwds):
    """wrapper that logs entry/exit"""
    log = SL_Logging.getLogger('update_manager')
    log.debug("update_manager(%s)" %
              ", ".join(itertools.chain((repr(arg) for arg in args),
                                        ("%s=%r" % item for item in kwds.items()))))
    result = _update_manager(*args, **kwds)
    log.debug("update_manager() => %r" % result)
    return result

def _update_manager(viewer_binary, cli_overrides = {}):
    """
    Pass:
    viewer_binary: string pathname of the existing viewer executable, the one
                   installed along with this SL_Launcher instance
    cli_overrides: a dict containing command-line switches

    Return:
    - string pathname of the executable to launch

    Raises UpdateError in various failure cases.
    """
    log = SL_Logging.getLogger('update_manager')
    InstallerUserMessage.status_message("Checking for updates\n"
                                        "This may take a few moments...")

    # cli_overrides is a dict where the keys are specific parameters of interest and the values are the arguments to 
    # comments that begin with ' ' are steps taken from the algorithm in the description of SL-323. 
    #   Note that in the interest of efficiency, such as determining download success once at the top
    #  The code does follow precisely the same order as the algorithm.

    #setup and getting initial parameters
    platform_key = Application.platform_key() # e.g. "mac"
    settings = get_settings(cli_overrides.get('settings') or Application.user_settings_path())

    #  If a complete download of that update is found, check the update preference:
    #settings['UpdaterServiceSetting'] =
    INSTALL_MODE_AUTO=3            # Install each update automatically
    INSTALL_MODE_PROMPT_OPTIONAL=1 # Ask me when an optional update is ready to install
    INSTALL_MODE_MANDATORY_ONLY=0  # Install only mandatory updates
    # (see panel_preferences_setup.xml)
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
    #    (the 'int()' is because a cli override is a string value)
    cli_settings = cli_overrides.get('set', {})
    cli_updater_service_setting = cli_settings.get('UpdaterServiceSetting',None)
    install_mode = int(cli_updater_service_setting if cli_updater_service_setting else settings.get('UpdaterServiceSetting', {}).get('Value', INSTALL_MODE_AUTO))
    # validate the install_mode
    if install_mode not in (INSTALL_MODE_AUTO, INSTALL_MODE_PROMPT_OPTIONAL, INSTALL_MODE_MANDATORY_ONLY):
        log.error("Invalid setting value for UpdaterServiceSetting (%d); using automatic install (%d)" % (install_mode, INSTALL_MODE_AUTO))
        install_mode = INSTALL_MODE_AUTO

    #use default chunk size if none is given, set UpdaterWillingToTest to None if not given
    #this is to prevent key errors on accessing keys that may or may not exist depending on cli options given
    # "chunk_size" ? "UpdaterMaximumBandwidth" ? Are these the same thing?
    cli_chunk_size_setting = cli_settings.get('UpdaterMaximumBandwidth', None)
    chunk_size = int(cli_chunk_size_setting if cli_chunk_size_setting else 1024 * 10)
    UpdaterWillingToTest = cli_settings.get('UpdaterWillingToTest')
    UpdaterServiceURL = cli_settings.get('UpdaterServiceURL')

    # get channel and version
    default_channel = BuildData.get('Channel')
    # we send the override to the VVM, but retain the default_channel version for in_place computations
    # note that this get() intentionally conflates the case of 'no channel
    # key' with 'not bool(value of channel key)'
    channel = cli_overrides.get('channel')
    if channel and channel != default_channel:
        log.info("Overriding channel '%s' with '%s' from command line" %
                 (default_channel, channel))
        BuildData.override('Channel', channel)

    #log.debug("Pre query settings:\n%s", pformat(settings)) # too big to leave this in all the time

    #  On launch, the Viewer Manager should query the Viewer Version Manager update api.
    result_data = query_vvm(platform_key=platform_key,
                            settings=settings,
                            UpdaterServiceURL=UpdaterServiceURL,
                            UpdaterWillingToTest=UpdaterWillingToTest)

    #nothing to do or error
    if not result_data:
        log.info("No update.")

        # clean up any previous download dir on windows, see apply_update.apply_update()
        try:
            if platform_key == 'win':
                past_download_dir = make_download_dir(BuildData.get('Version'))
                #call make to convert our version into a previous download dir path
                #call check to see if the winstall file is there
                installed = check_for_completed_download(past_download_dir)
                log.debug("Checked for previous Windows install in %s with result %s." %
                          (past_download_dir, installed))
                if installed == 'winstall':
                    log.info("Cleaning up past download directory '%s'" % past_download_dir)
                    shutil.rmtree(past_download_dir)
        except Exception as e:
            #cleanup is best effort
            log.error("Caught exception cleaning up download dir '%r'; skipping" % e)
            pass

        # run already-installed viewer
        return viewer_binary

    chosen_result = choose_update(platform_key, settings, result_data)
    if not chosen_result:
        # We didn't find anything better than what we've got, so run that
        return viewer_binary

    log.debug("Chosen result %r" % chosen_result)

    # Here we believe we need an update.
    # check to see if user has install rights
    # get the owner of the install and the current user
    # none of this is supported by Python on Windows
    try:
        script_owner_id = os.stat(os.path.realpath(__file__)).st_uid
        user_id = os.getuid()
        if script_owner_id != user_id:
            import pwd
            script_owner_name = pwd.getpwuid(script_owner_id)[0]
            username = pwd.getpwuid(user_id)[0]
            log.info("Upgrade notification attempted by user " + username)    
            frame = InstallerUserMessage.InstallerUserMessage(title = "Second Life Installer")
            frame.binary_choice_message(message = "Second Life was installed by userid " + script_owner_name 
                + ".  Do you have privileges to install?", true = "Yes", false = 'No')
            if not frame.choice.get():
                log.info("Upgrade attempt declined by user " + username)
                InstallerUserMessage.basic_message(
                    "Please find a system admin to upgrade Second Life")
                return viewer_binary
    except (AttributeError, ImportError):
        #Windows throws AttributeError on getuid() and ImportError on pwd
        #Just ignore it and consider the ID check as passed.
        pass

    #get download directory, if there are perm issues or similar problems, give up
    try:
        download_dir = make_download_dir(chosen_result['version'])
    except Exception as e:
        log.error("Error trying to make download dir %r" % e)
        return viewer_binary
    
    # determine if we've tried this download before
    downloaded = check_for_completed_download(download_dir, chosen_result['size'])

    #  If the response indicates that there is a required update: 
    if chosen_result['required']:
        log.info("Required update to %s version %s" % (chosen_result['platform'], chosen_result['version']))
        #  Check for a completed download of the required update; if found, display an alert, install the required update, and launch the newly installed viewer.
        #  If [optional download and] Install Automatically: display an alert, install the update and launch updated viewer.
        if downloaded is None:
            # start the download, exception if we fail
            download(url = chosen_result['url'],
                     version = chosen_result['version'],
                     download_dir = download_dir,
                     hash = chosen_result['hash'],
                     size = chosen_result['size'],
                     background = False,
                     chunk_size = chunk_size)
        # Do the install
        return install(platform_key = platform_key, download_dir = download_dir)
    else:
        # If the update response indicates that there is an optional update: 
        # Check to see if the optional update has already been downloaded.
        # If a complete download of that update is found, check the update preference: 
        # Note: automatic install handled above as the steps are the same as required upgrades
        # If Install Manually: display a message with the update information and ask the user whether or not to install the update with three choices:
        # Skip this update: create a marker that subsequent launches should not prompt for this update as long as it is optional, 
        # but leave the download in place so that if it becomes required it will be there.
        # Install next time: create a marker that skips the prompt and installs on the next launch
        # Install and launch now: do it.
        log.info("Found optional update. Download directory is: " + download_dir)
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
            download(url = chosen_result['url'],
                     version = chosen_result['version'],
                     download_dir = download_dir,
                     hash = chosen_result['hash'],
                     size = chosen_result['size'],
                     background = True)
            # run the previously-installed viewer
            return viewer_binary
        elif downloaded == 'done' or downloaded == 'next':
            log.info("Found previously downloaded update in: " + download_dir)

            if INSTALL_MODE_AUTO == install_mode:
                log.info("updating automatically")
                return install(platform_key = platform_key, download_dir = download_dir)

            elif INSTALL_MODE_PROMPT_OPTIONAL == install_mode:
                # ask the user what to do with the optional update
                log.info("asking the user what to do with the update")
                skip_frame = InstallerUserMessage.InstallerUserMessage(
                    title = BuildData.get('Channel Base')+" Installer")
                skip_frame.trinary_choice_link_message(
                    message = "Update %s is ready to install.\n"
                    "Release Notes:\n%s" % (chosen_result['version'],chosen_result['more_info']),
                    url = str(chosen_result['more_info']),
                    one = "Install", two = "Skip", three = "Not Now")
                update_action = skip_frame.choice3.get()
                if update_action == 1:
                    log.info("User chose 'Install'")
                    return install(platform_key = platform_key, download_dir = download_dir)
                elif update_action == 2:
                    log.info("User chose 'Skip'")
                    put_marker_file(download_dir, ".skip")
                    # run previously-installed viewer
                    return viewer_binary
                else:                       # Not Now
                    log.info("User chose 'Not Now'")
                    put_marker_file(download_dir, ".next")
                    # run previously-installed viewer
                    return viewer_binary
            else: # INSTALL_MODE_MANDATORY_ONLY
               log.info("not installing optional update per UpdaterServiceSetting")
               return viewer_binary

        elif downloaded == 'skip':
            log.info("Skipping this update per previous choice.  "
                     "Delete the .skip file in " + download_dir + " to change this.")
            # run previously-installed viewer
            return viewer_binary
        else:
            #shouldn't be here
            log.error("Found nonempty download dir but no flag file. Check returned: %r" %
                        downloaded)
            return viewer_binary

if __name__ == '__main__':
    #this is mostly for testing on Windows, emulating exe enviroment with $python scriptname
    if 'ython' in sys.executable:
        sys.executable =  os.path.abspath(sys.argv[0])
    #there is no argument parsing or other main() work to be done
    # Initialize the python logging system to SL Logging format and destination
    log = SL_Logging.getLogger('SL_Updater')
    try:
        viewer_binary = os.path.join(os.path.dirname(sys.executable), Application.name())
        update_manager(viewer_binary)
    except Exception:
        log.exception("Unhandled exception")
