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

from logging import DEBUG
from util import Application, BuildData, SL_Logging, log_calls, pass_logger, subprocess_args, \
     put_marker_file, MergedSettings, ufile
from llbase import llsd, llrest

import apply_update
import download_update
import errno
import glob
import hashlib
import InstallerUserMessage
import json
import os
import os.path
from pprint import pformat
import re
import platform
from runner import PopenRunner
import shutil
import subprocess
import sys
import tempfile
import threading
# specifically import the sleep() function for testability
from time import sleep
#for the quote method
import urllib
#for the disable_warnings method 
import urllib3
import uuid
import warnings
from xml.etree import ElementTree

DEFAULT_UPDATE_SERVICE = 'https://update.secondlife.com/update'

class UpdateError(Exception):
    pass

class WmicError(UpdateError):
    pass

#module globals

def md5file(fname):
    with open(fname, "rb") as f:
        return md5handle(f)

def md5handle(handle):
    #utility method to compute the checksum of the contents of a file
    hash_md5 = hashlib.md5()
    #unit tests use tempfile temporary files which return handles to files that vanish if you
    #close the handle while Windows will say permission denied to a second handle.
    for chunk in iter(lambda: handle.read(4096), b""):
        hash_md5.update(chunk)
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
    # TODO: It's not clear what value .next actually adds.
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
              download_dir, installer, samples[1], expected_size)
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
    #return the settings file parsed into a MergedSettings object
    settings={}
    log=SL_Logging.getLogger('get_settings')

    try:
        settings = llsd.parse(open(settings_file, 'rb').read())
    except llsd.LLSDParseError as lpe:
        log.warning("Could not parse settings file %r: %s", os.path.abspath(settings_file), lpe)
    except OSError as err:
        if err.errno == errno.ENOENT:
            log.info("No settings file at %r", os.path.abspath(settings_file))
        else:
            log.warning("OS error reading settings file %r: %s" % (os.path.abspath(settings_file), e))
    except Exception as e:
        log.warning("Could not read settings file %r: %s", os.path.abspath(settings_file), e)
    else:
        log.debug("Loaded viewer settings from %r", os.path.abspath(settings_file))
    return MergedSettings(settings)

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
        try:
            # wmic csproduct get UUID | grep -v UUID
            muuid = wmic('csproduct','get','UUID')
        except WmicError as err:
            log.warning(err)
            muuid = None
        else:
            #outputs two visible rows:
            #UUID
            #XXXXXXX-XXXX...
            # but splitlines() produces a whole lot of empty strings.
            muuid = [line for line in muuid.splitlines() if line][-1].rstrip()
            log.debug("result of subprocess call to get win MUUID: %r" % muuid)
            
    if muuid is None:
        #fake it
        log.info("Unable to get system unique id; constructing a dummy")
        muuid = str(uuid.uuid1())
    hash = hashlib.md5(muuid).hexdigest()
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
    try:
        # MAINT-9014: There are a couple possibilities for finding wmic.
        try:
            # It has a canonical pathname that might or might not be on the PATH.
            return _wmic("c:/Windows/System32/Wbem/wmic", *args)
        except WindowsError as err:
            # Only retry for "not found" -- anything else is a genuine problem.
            if err.errno != errno.ENOENT:
                raise
            # wmic not in usual place -- better hope it's on PATH! Let any
            # exceptions from this call propagate to outer 'try'.
            # Tempting though it is to memoize the knowledge that the usual
            # path doesn't work, the fact is that we only invoke wmic a couple
            # times.
            return _wmic("wmic", *args)
    except subprocess.CalledProcessError as err:
        # https://docs.python.org/2/library/subprocess.html#subprocess.CalledProcessError
        # When check_output() raises CalledProcessError, it stores collected
        # output into err.output.
        raise WmicError("wmic error: %s\n%s" % (err, err.output))
    except WindowsError as winerr:
        if winerr.errno == errno.ENOENT:
            raise WmicError("No wmic command found - bad Windows install?")
        raise WmicError("wmic command failed; error %s %s" % (winerr.winerror, winerr.strerror))

def _wmic(*wmic_cmd):
    return subprocess.check_output(
        wmic_cmd,
        **subprocess_args(include_stdout=False,
                          log_stream=SL_Logging.stream_from_process(wmic_cmd)))

@pass_logger
def query_vvm_from_settings(log, platform_key, settings):
    """
    Ask the viewer version manager what builds are available for me
    given my platform and version.
    Returns a map of all responses.
    """
    # URI template /update/v1.2/channelname/version/platform/platformversion/willing-to-test/uniqueid
    # https://lindenlab.atlassian.net/wiki/spaces/SLT/pages/71106564/Viewer+Version+Manager+REST+API
    # See https://lindenlab.atlassian.net/wiki/spaces/SLT/pages/466081/Viewer+Version+Manager+in+AWS
    channelname = BuildData.get('Channel')

    UpdaterWillingToTest = settings.get('UpdaterWillingToTest', 1)
    try:
        # convert "0" or "1" to corresponding integer
        UpdaterWillingToTest = int(UpdaterWillingToTest)
    except ValueError:
        try:
            # special form permitted only on command line
            UpdaterWillingToTest = dict(testok=1, testno=0)[UpdaterWillingToTest]
        except KeyError:
            bad = UpdaterWillingToTest
            UpdaterWillingToTest = 1
            log.error("Invalid value for UpdaterWillingToTest, assuming %s: %r",
                      UpdaterWillingToTest, bad)

    UpdaterServiceURL = settings.get('UpdaterServiceURL')
    if not UpdaterServiceURL:
        UpdaterServiceURL=os.getenv('SL_UPDATE_SERVICE',
            BuildData.get('Update Service', DEFAULT_UPDATE_SERVICE))

    return query_vvm(platform_key=platform_key,
                     channel=channelname,
                     UpdaterWillingToTest=UpdaterWillingToTest,
                     UpdaterServiceURL=UpdaterServiceURL)

@pass_logger
def query_vvm(log, platform_key, channel, UpdaterWillingToTest, UpdaterServiceURL):
    version = BuildData.get('Version')

    #suppress warning we get in dev env for altname cert 
    if UpdaterServiceURL != DEFAULT_UPDATE_SERVICE:
        warnings.simplefilter('ignore', urllib3.exceptions.SecurityWarning)

    bitness = getBitness(platform_key)

    # Ask the VVM with the most specific form of our platform (including bitness)
    # so that if it can be configured with more specific rules
    VVM_platform = "%s%d" % (platform_key, bitness)

    # we need to use the dotted versions of the platform versions in order to be compatible with VVM rules and arithmetic
    if platform_key == 'win':
        platform_version = platform.win32_ver()[1]
    elif platform_key == 'mac':
        platform_version = platform.mac_ver()[0]
    else:
        platform_version = platform.release()
    #this will always return something usable, error handling in method
    UUID = str(make_VVM_UUID_hash(platform_key))

    # UpdaterWillingToTest is either 0 or 1
    test_ok = 'testok' if UpdaterWillingToTest else 'testno'
    log.debug("UpdaterWillingToTest = %r, test_ok = %r", UpdaterWillingToTest, test_ok)
    
    log.info("Requesting update for channel '%s' version %s platform %s platform version %s allow_test %s id %s" %
             (channel, version, VVM_platform, platform_version, test_ok, UUID))
    update_urlpath =  urllib.quote('/'.join(['v1.2', channel, version, VVM_platform, platform_version, test_ok, UUID]))
    # if debugging, ask the VVM to explain how it got the response
    debug_param= {'explain': 1} if log.isEnabledFor(DEBUG) else {}
    log.debug("Sending query to VVM: query %s/%s%s",
              UpdaterServiceURL, update_urlpath,
              (" with explain requested" if debug_param else ""))
    VVMService = llrest.SimpleRESTService(name='VVM', baseurl=UpdaterServiceURL)
    
    try:
        result_data = VVMService.get(update_urlpath, params=debug_param)
    except llrest.RESTError as res:
        if res.status == 404: # 404 is how the Viewer Version Manager indicates that the channel is unmanaged
            log.info("Update service returned 'not found'; normally this means the channel is unmanaged (and allowed)")
        else:
            log.warning("Update service %s/%s failed: %s", UpdaterServiceURL, update_urlpath, res)
        return None

    log.debug("received result from VVM: %r" % result_data)
    # logging the explanation above is enough, not needed elsewhere
    result_data.pop('explain', None)
    return result_data

class WindowsVideo(object):
    hasOnlyUnsupported = None # so that we only call wmic once

    # Empirically, we find that the 64-bit viewer will not run on certain versions
    # of Windows with certain graphics cards. This module contains logic to detect
    # those situations and specifically run the 32-bit viewer.
    #This is an exclusion list created by experimental techniques
    #and research that is extrinsic to VMP.  64bit viewer does not run on these.
    #
    #Also, only some HDs are bad, unfortunately, some of the bad ones have no model number
    #so instead of 'Intel(R) HD Graphics 530' we just get 'Intel(R) HD Graphics'
    #hence the strange equality test for 'Graphics' when we pop the last word off the string.
    NO64_GRAPHICS_LIST = ['Graphics', '2000', '2500', '3000', '4000']

    @staticmethod
    def onNo64Windows():
        if platform.system() != 'Windows':
            return False
        log = SL_Logging.getLogger('onNo64Windows')
        windowsVersion = platform.win32_ver()[1]
        versionPair = [int(field) for field in windowsVersion.split('.')[:2]]
        # As far as we know, Intel doesn't have (working) drivers for the cards in
        # NO64_GRAPHICS_LIST specifically on Windows 10 and Windows 8.1. According
        # to this page:
        # https://msdn.microsoft.com/en-us/library/windows/desktop/ms724832(v=vs.85).aspx
        # that would be every version >= [6, 3].
        no64 = (versionPair >= [6, 3])
        log.debug("Windows version %s should%s be okay", windowsVersion,
                  (" not" if no64 else ""))
        return no64

    @staticmethod
    def isUnsupported():
        if WindowsVideo.hasOnlyUnsupported is None:
            log = SL_Logging.getLogger('windows_video')

            # There are video cards that are not supported for the 64bit build on Windows 10,
            # so find out what the video controller is
            try:
                wmic_graphics = wmic('path','Win32_VideoController','get','NAME')
            except WmicError as err:
                log.warning(err)
                # MAINT-8200: If we can't get information about the video
                # card, conservatively assume we'll need the 32-bit viewer.
                # The downside if we guess wrong is a performance hit, which
                # can be overridden by the ForceAddressSize parameter. If we
                # guess the other way, the downside is a viewer crash.
                WindowsVideo.hasOnlyUnsupported = True
            else:
                log.debug("wmic graphics card info: %r", wmic_graphics)
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
                                          line.split()[-1] in WindowsVideo.NO64_GRAPHICS_LIST)]
                    # There's no order guarantee from wmic, this is to prevent an
                    # HD card discovered after a good card from overwriting the state variable
                    # by specification, a machine is bad iff ALL of the cards on the machine are bad ones
                    if good_cards:
                        WindowsVideo.hasOnlyUnsupported = False
                        log.debug("Found at least one good graphics card: '%s'",
                                  "', '".join(good_cards))
                    else:
                        # all we found were cards that are not supported in the Windows 64bit build
                        WindowsVideo.hasOnlyUnsupported = True
                        log.warning("Found only graphics cards not supported in Windows 8.1 or 10: "
                                    "'%s'; should switch to the 32 bit build",
                                    "', '".join(wmic_list))
                else:
                    log.warning("wmic did not return any video cards")
                    # use MAINT-8200 reasoning described above
                    WindowsVideo.hasOnlyUnsupported = True

        return WindowsVideo.hasOnlyUnsupported

@pass_logger
def choose_update(log, platform_key, ForceAddressSize, vvm_response):
    """
    This is where we do the hard stuff - picking which result applies to this system

    Returns a chosen result dict with keys:
       required, channel, version, url, size, hash, more_info, platform
    or, if no update is chosen, an empty dict
    """
    chosen_result = dict()

    current_build = "%s%d" % (BuildData.get('Platform'), int(BuildData.get('Address Size')))
    target_platform = "%s%d" % (platform_key, getBitness(platform_key))
    log.debug("Current build is %s; tentative target is %s" % (current_build, target_platform))

    if platform_key == 'win':
        # for Windows, there's more to it than that....
        if current_build == 'win64' and target_platform == 'win32':
            log.info("This is a 64 bit build, but this system is 32 bit; looking for a 32 bit build")

        elif target_platform == 'win64' and WindowsVideo.onNo64Windows() and WindowsVideo.isUnsupported():
            log.warning("Your video card(s) are not supported for 64-bit on Windows 8.1 or 10; "
                        "switching you to the 32bit build, "
                        "which runs in a compatibility mode that works better")
            target_platform = 'win32'

    # We could have done this check earlier, but by waiting we can make the warnings more specific
    if ForceAddressSize:
        try:
            forced_bitness = int(ForceAddressSize)
        except ValueError:
            log.warning("Invalid value %r for ForceAddressSize setting; disregarding",
                        ForceAddressSize)
        else:
            log.debug("ForceAddressSize setting: %d", forced_bitness)
            if target_platform == 'win32' and forced_bitness == 64:
                log.warning("ForceAddressSize 64 may not work, but trying anyway...")
                target_platform = 'win64'
            elif target_platform == 'win64' and forced_bitness == 32:
                log.warning("ForceAddressSize 32: your system may work with 64 - consider omitting")
                target_platform = 'win32'
            else:
                log.info("target platform is %s, ForceAddressSize is %d; no effect",
                         target_platform, forced_bitness)

    # Ok... now we know what the target_platform is ...

    # Get all the VVM results that are not platform dependent
    for key in ['required', 'version', 'channel', 'more_info']:
        try:
            chosen_result[key] = vvm_response[key]
        except KeyError:
            log.error("Viewer Version Manager response is missing '%s'; not updating" % key)
            return {}

    if target_platform != current_build:
        log.info("Current build platform is '%s', but we need '%s', so update is required",
                 current_build, target_platform)
        chosen_result['required'] = True

    elif vvm_response['version'] == BuildData.get('Version'):
        log.info("Current version and platform matches this build; no update")
        return {}

    # We believe we have at least an optional update, so fill in the rest of chosen_result
    platforms = vvm_response.get('platforms', {})
    # See if the VVM gave us a result for the target_platform; if not, check
    # to see if a result not qualified by address_size is in the results
    try:
        target_result = platforms[target_platform]
    except KeyError:
        try:
            target_result = platforms[platform_key]
        except KeyError:
            log.warning("No update result found for '%s' or '%s'" % (target_platform, platform_key))
            return {}
        else:
            log.warning("No update result found for '%s' but found '%s', so updating to that",
                        target_platform, platform_key)
            target_platform = platform_key

    # add the target we picked
    chosen_result['platform'] = target_platform
    chosen_result.update(target_result)

    return chosen_result

def download(url, version, download_dir, size, hash, ui):
    log=SL_Logging.getLogger('download')

    ground = "foreground" if ui else "background"

    log.info("Preparing to download new version %s to %s in %s",
             version, download_dir, ground)
    #three strikes and you're out
    for download_tries in xrange(3):
        download_args = dict(url = url, download_dir = download_dir, size = size,
                             progressbar=ui)
        log.debug("%s%s downloader args: %r",
                  ("trying again -- " if download_tries else ""),
                  ground, download_args)
        # If ui, we're asking download_update() to put up a
        # progress bar. Don't also put up a status message; it would only
        # flicker briefly before the progress bar frame is displayed.
        try:
            filename = download_update.download_update(**download_args)
        except Exception as e:
            log.error("Failed to download new version %s in %s downloader: %s: %s",
                      version, ground, e.__class__.__name__, e)
        else:
            #check to make sure the downloaded file is correct
            down_hash = md5file(filename)
            if down_hash == hash:
                # once we succeed, stop (re)trying
                return filename
            #try again
            log.warning("Hash mismatch: Expected: %s Received: %s" % (hash, down_hash))

    else:
        # we got through the whole for loop without once succeeding
        message = "Failed to download new version %s from %s. Please check connectivity." % \
                  (version, url)
        log.error(message)
        if ui:
            InstallerUserMessage.basic_message(message)

        raise UpdateError(message)

@pass_logger
def install(log, command, platform_key, installer):
    InstallerUserMessage.status_message("New version downloaded.\n"
                                        "Installing now, please wait.")
    # We expect the new installer to be located in a directory whose name is
    # the version to which we're updating. That's okay because we only use
    # 'version' for informational messages anyway.
    download_dir = os.path.dirname(installer)
    version = os.path.basename(download_dir)
    try:
        runner = apply_update.apply_update(command, installer, platform_key)
    except apply_update.ApplyError as err:
        InstallerUserMessage.basic_message("Failed to apply " + version)
        log.warning("Failed to update viewer to " + version)
        raise UpdateError("Failed to apply version %s update: %s" %
                          (version, err))

    #windows is cleaned up on the following run, see apply_update.apply_update()
    if platform_key != 'win':
        shutil.rmtree(download_dir)
    #this is the path to the new install
    return runner

@log_calls
@pass_logger
def update_manager(log, command, cli_overrides = {}):
    """
    Pass:
    command:       list starting with pathname of the existing viewer
                   executable, the one installed along with this SL_Launcher
                   instance, followed by command-line arguments
    cli_overrides: a dict containing VMP-relevant command-line switches

    Return:
    - Runner instance whose run() method will launch the viewer (or its
      installer)

    Raises UpdateError in various failure cases.
    """
    InstallerUserMessage.status_message("Checking for updates\n"
                                        "This may take a few moments...")

    # It is reported that on Windows 10, some graphics cards cannot deal with
    # our viewer's video benchmarking -- but that if we skip it, things run
    # okay.
    # TODO: If we suppress this on the initial run, but the user subsequently
    # updates their OS or graphics card so that we can and should perform
    # graphics benchmarking, need to rerun in updater.leap() so we can unsuppress.
    if WindowsVideo.onNo64Windows() \
      and int(BuildData.get('Address Size')) == 64 \
      and WindowsVideo.isUnsupported():
        log.info("Windows 8.1 and 10 do not support the video card; "
                 "setting option to skip video benchmarking")
        # This isn't a user setting! If two Windows users share a machine, and
        # one installs the viewer and sets SkipBenchmark = True (but in user
        # settings), the second user's viewer run will still attempt graphics
        # benchmarking and crash. Set it in settings_install.xml.
        # This logic assumes that we're running at the same level of
        # administrative privilege as the NSIS installer itself: that if the
        # installer can write to the application directory, so can we.
        install_settings_file = os.path.join(Application.app_data_path(),
                                             'app_settings', 'settings_install.xml')
        try:
            # Does this user already have a settings_install file?
            with open(install_settings_file, 'rb') as inf:
                install_settings = llsd.parse(inf.read())
        except (IOError, OSError, llsd.LLSDParseError) as err:
            # There's no such file, or the file exists but is garbled.
            # So we'll have to write it from scratch -- no prior settings.
            install_settings = {}
            log.debug("No previous settings_install.xml file, proceeding: %s: %s",
                      err.__class__.__name__, err)
        else:
            log.debug("Read existing install settings file at %s", install_settings_file)

        try:
            # Get the previously-saved SkipBenchmark setting.
            SkipBenchmark = install_settings['SkipBenchmark']
        except KeyError:
            # That setting is not in this file. Retrieve the definition
            # for the SkipBenchmark setting from app_settings/settings.xml.
            app_settings_file  = os.path.join(Application.app_data_path(),
                                              'app_settings', 'settings.xml')
            log.debug("No previous SkipBenchmark setting; trying %s",
                      app_settings_file)
            try:
                with open(app_settings_file, 'rb') as inf:
                    SkipBenchmark = llsd.parse(inf.read())['SkipBenchmark']
            except (IOError, OSError, llsd.LLSDParseError, KeyError) as err:
                # This is more serious: can't read app_settings/settings.xml?!
                # Or it's garbled, or there's no such setting? Fake it.
                SkipBenchmark = dict(
                    Comment='if true, disables running the GPU benchmark at startup\n'
                    '      (default to class 1)',
                    Persist=True,
                    Type='Boolean',
                    Value=True)
                log.debug("Can't get SkipBenchmark definition from %s: %s: %s; "
                          "using fake SkipBenchmark: %s",
                          app_settings_file, err.__class__.__name__, err, SkipBenchmark)
            else:
                # We DID retrieve SkipBenchmark from app_settings.
                log.debug("Using SkipBenchmark from %s: %s", app_settings_file, SkipBenchmark)
        else:
            log.debug("Using SkipBenchmark from %s: %s", install_settings_file, SkipBenchmark)

        # By hook or by crook, we now have a plausible definition for the
        # SkipBenchmark setting. Set it True for this user.
        SkipBenchmark['Value'] = True
        # Set this modified SkipBenchmark setting into settings_install.
        install_settings['SkipBenchmark'] = SkipBenchmark
        # (re)write the settings_install file
        try:
            with open(install_settings_file, 'wb') as outf:
                outf.write(llsd.format_pretty_xml(install_settings))
        except (OSError, IOError) as err:
            log.warning("Can't update %s: %s: %s", install_settings_file,
                        err.__class__.__name__, err)
        else:
            log.debug("Wrote updated settings to %s", install_settings_file)

    # we end up running the existing viewer in many cases
    existing_viewer = PopenRunner(*command)

    # cli_overrides is a dict where the keys are specific parameters of interest and the values are the arguments

    #setup and getting initial parameters
    platform_key = Application.platform_key() # e.g. "mac"
    settings = get_settings(cli_overrides.get('settings') or Application.user_settings_path())

    # 'settings' is from the settings file. Now apply command-line overrides.
    settings.override_with(cli_overrides.get('set', {}))

    # If cli_overrides['set']['UpdaterServiceSetting'], use that; else if
    # settings['UpdaterServiceSetting']['Value'], use that; if none of the
    # above, or if value is not valid, use default from decode_install_mode().
    install_key = settings.get('UpdaterServiceSetting')
    install_mode = decode_install_mode(install_key)

    # get channel
    default_channel = BuildData.get('Channel')
    channel = cli_overrides.get('channel')
    if channel and channel != default_channel:
        log.info("Overriding channel '%s' with '%s' from command line" %
                 (default_channel, channel))
        BuildData.override('Channel', channel)

    #log.debug("Pre query settings:\n%s", pformat(settings)) # too big to leave this in all the time

    #  On launch, the Viewer Manager should query the Viewer Version Manager update api.
    result_data = query_vvm_from_settings(platform_key=platform_key,
                                          settings=settings)

    #nothing to do or error
    if not result_data:
        log.info("No update.")
        cleanup_previous_download(platform_key)
        # run already-installed viewer
        return existing_viewer

    ForceAddressSize = settings.get('ForceAddressSize')
    chosen_result = choose_update(platform_key, ForceAddressSize, result_data)
    if not chosen_result:
        cleanup_previous_download(platform_key)
        # We didn't find anything better than what we've got, so run that
        return existing_viewer

    log.debug("Chosen result %r" % chosen_result)

    # Here we believe we need an update.
    # check to see if user has install rights
    if not check_install_privs():
        return existing_viewer

    #get download directory, if there are perm issues or similar problems, give up
    try:
        download_dir = make_download_dir(chosen_result['version'])
    except Exception as e:
        log.error("Error trying to make download dir: %s: %s", e.__class__.__name__, e)
        return existing_viewer

    # determine if we've tried this download before
    downloaded = check_for_completed_download(download_dir, chosen_result['size'])

    #  If the response indicates that there is a required update: 
    if chosen_result['required']:
        log.info("Required update to %s version %s" % (chosen_result['platform'], chosen_result['version']))
        #  Check for a completed download of the required update; if found, display an alert, install the required update, and launch the newly installed viewer.
        #  If [optional download and] Install Automatically: display an alert, install the update and launch updated viewer.
        if downloaded is None:
            # start the download, exception if we fail
            installer = download(url = chosen_result['url'],
                                 version = chosen_result['version'],
                                 download_dir = download_dir,
                                 hash = chosen_result['hash'],
                                 size = chosen_result['size'],
                                 ui = True)
        else:
            installer = apply_update.get_filename(download_dir)
        # Do the install
        return install(command, platform_key = platform_key, installer=installer)
    elif 'Install_manual' == install_mode:
        # The user has chosen to install only required updates, and this one is optional,
        # so just run the already-installed viewer. We don't even download the optional
        # viewer, so chances are they will have to wait for the download if it eventually
        # becomes mandatory
        log.info("not installing optional update per UpdaterServiceSetting")
        return existing_viewer
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
            log.info("Found optional update. Downloading in background to: " + download_dir)
            # Create and launch a background thread. Because we do NOT set
            # this thread as daemon, the process won't terminate until the
            # thread completes.
            background = threading.Thread(
                name="downloader",
                target=download,
                kwargs=dict(url = chosen_result['url'],
                            version = chosen_result['version'],
                            download_dir = download_dir,
                            hash = chosen_result['hash'],
                            size = chosen_result['size'],
                            ui=False))
            background.start()
            # run the previously-installed viewer
            return existing_viewer
        elif downloaded == 'done' or downloaded == 'next':
            log.info("Found previously downloaded update in: " + download_dir)
            installer = apply_update.get_filename(download_dir)

            if 'Install_automatically' == install_mode:
                log.info("updating automatically")
                return install(command, platform_key = platform_key, installer=installer)

            else: # 'Install_ask'
                # ask the user what to do with the optional update
                log.info("asking the user what to do with the update")
                update_action = InstallerUserMessage.trinary_choice_message(
                    message = "Update %s is ready to install.\n"
                    "Release Notes:\n%s" % (chosen_result['version'],chosen_result['more_info']),
                    url = str(chosen_result['more_info']),
                    one = "Install", two = "Skip", three = "Not Now")
                update_action = skip_frame.choice3.get()
                if update_action == 1:
                    log.info("User chose 'Install'")
                    return install(command, platform_key = platform_key, installer=installer)
                elif update_action == 2:
                    log.info("User chose 'Skip'")
                    put_marker_file(download_dir, ".skip")
                    # run previously-installed viewer
                    return existing_viewer
                else:                       # Not Now
                    log.info("User chose 'Not Now'")
                    put_marker_file(download_dir, ".next")
                    # run previously-installed viewer
                    return existing_viewer

        elif downloaded == 'skip':
            log.info("Skipping this update per previous choice.  "
                     "Delete the .skip file in " + download_dir + " to change this.")
            # run previously-installed viewer
            return existing_viewer
        else:
            #shouldn't be here
            log.error("Found nonempty download dir but no flag file. Check returned: %r" %
                        downloaded)
            return existing_viewer

@pass_logger
def decode_install_mode(log, install_key):
    """
    Given (the string form of) one of the numeric codes representing an
    install_mode choice on the Preferences floater, return the corresponding
    internal name string, one of:

    Install_automatically
    Install_ask
    Install_manual

    If you pass None (or an invalid key), you get the default: Install_automatically.
    """
    # Track the real preferences control settings used by the viewer.
    panel_file = os.path.join(Application.app_data_path(),
                              'skins', 'default', 'xui', 'en', 'panel_preferences_setup.xml')
    root = ElementTree.parse(panel_file).getroot()
    # Look for the combo_box for the UpdaterServiceSetting control,
    # specifically the items defined for that combo_box.
    # https://docs.python.org/2/library/xml.etree.elementtree.html#xpath-support
    # Construct a dict { string_value : (internal_name, user_text) }.
    install_modes = {
        item.get('value'): (item.get('name'), item.get('label'))
        for item in
        root.findall('./combo_box[@control_name="UpdaterServiceSetting"]/combo_box.item') }

    # Look up key in install_modes
    try:
        install_modes[install_key]
    except KeyError:
        # For this one item we must perform a reverse lookup -- but with only a
        # handful of items, a linear search suffices.
        Install_automatically = next(key for (key, (internal, user)) in install_modes.items()
                                     if internal == 'Install_automatically')
        # install_key can be passed as None if nobody has tried to set it. We
        # know None is an invalid setting; it's only an error if somebody set
        # some other invalid value.
        logfunc = log.info if install_key is None else log.error
        logfunc("Invalid setting value for UpdaterServiceSetting (%s); falling back to auto (%s)",
                install_key, Install_automatically)
        install_key = Install_automatically
    # Now convert to the internal string to defend against possible changes to the
    # meaning of the value.
    install_mode, install_desc = install_modes[install_key]
    log.info("Update mode (UpdaterServiceSetting) is %s (%s)", install_desc, install_key)
    return install_mode

@pass_logger
def check_install_privs(log):
    # Can the current user overwrite the viewer executable?
    # (We don't test __file__ because, in a PyInstaller environment, __file__
    # is a Python script unpacked into a temp directory, to which the current
    # process can certainly write -- since it already did! -- regardless of
    # the question of whether it has permissions to update the viewer install.)
    executable = Application.executable()
    if os.access(executable, os.W_OK):
        return True

    log.info("Current user does NOT have permission to update %s", executable)
    InstallerUserMessage.basic_message(
        "Please find a system admin to upgrade Second Life")
    return False

@pass_logger
def cleanup_previous_download(log, platform_key):
    # clean up any previous download dir on windows, see apply_update.apply_update()
    if platform_key == 'win':
        try:
            past_download_dir = make_download_dir(BuildData.get('Version'))
            #call make to convert our version into a previous download dir path
            #call check to see if the winstall file is there
            installed = check_for_completed_download(past_download_dir)
            log.debug("Checked for previous Windows install in %s with result %s." %
                      (past_download_dir, installed))
            if installed == 'winstall':
                log.info("Cleaning up past download directory %r" % past_download_dir)
                shutil.rmtree(past_download_dir)
        except Exception as e:
            #cleanup is best effort
            log.error("Caught exception cleaning up download dir %r: %s: %s; skipping",
                      past_download_dir, e.__class__.__name__, e)

if __name__ == '__main__':
    #there is no argument parsing or other main() work to be done
    # Initialize the python logging system to SL Logging format and destination
    log = SL_Logging.getLogger('SL_Updater')
    try:
        viewer_binary = Application.executable()
        update_manager(viewer_binary)
    except Exception:
        log.exception("Unhandled exception")
