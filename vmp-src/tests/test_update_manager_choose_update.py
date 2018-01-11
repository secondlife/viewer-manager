#!/usr/bin/env python

"""\
@file   test_update_manager_choose_update.py
@author oz
@date   2017-09-25

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


from nose.tools import assert_equal

import os
import sys
import platform
import shutil
import tempfile
from patch import patch, patch_dict, DELETE
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler

# when running individual test files, this is needed for the imports below
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_manager
from vmp_util import BuildData

VVM_RESULT = { 'required'  : False
              ,'version'   : '4.0.1.310054'
              ,'channel'   : 'Second Life Release'
              ,'more_info' : 'https://wiki.secondlife.com/wiki/Release_Notes/Second_Life_Release/4.0.1.310054'
              ,'platforms' :
              { 'win32' :
                    { 'url'  : 'http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_i686_Setup.exe'
                     ,'hash' : '08f65e80c15aa5dd9cacc1465000032'
                     ,'size' : 52100032
                     }
               ,'win64' :
                    { 'url'  : 'http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_x86_64_Setup.exe'
                     ,'hash' : '08f65e80c15aa5dd9cacc1465000064'
                     ,'size' : 52100064
                     }
               ,'win' :
                    { 'url'  : 'http://download.cloud.secondlife.com/FALLBACK/Second_Life_4_0_1_310054_x86_64_Setup.exe'
                     ,'hash' : '08f65e80c15aa5dd9cacc1465000f64'
                     ,'size' : 52100064
                     }
               ,'mac64' :
                    { 'url'  : 'http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_i386.dmg'
                     ,'hash' : '7f4fa9ff0ea20b0f6b4c907247d866b2'
                     ,'size' : 78364790
                     }
               ,'lnx64' :
                    { 'url'  : 'http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_i686.tar.bz2'
                     ,'hash' : '5c4108145f344b0cbe922182241005ed'
                     ,'size' : 41938388
                     }
              }
            }

def force(address_size):
    """convenience function for generating command-line overrides"""
    return dict(ForceAddressSize=str(address_size))

# These are used to mock update_manager.getBitness
# For the real test of that method, see test_update_manager_get_bitness.py
def bitness32(key):
    return 32

def bitness64(key):
    return 64

# These are used to mock the methods for interogating Windows versions and video cards
class Windows10VideoBadCards:
    @staticmethod
    def onWin10orGreater():
        return True

    @staticmethod
    def isUnsupported():
        return True

class Windows10VideoGoodCards:
    @staticmethod
    def onWin10orGreater():
        return True

    @staticmethod
    def isUnsupported():
        return False

class WindowsOldVideoBadCards:
    @staticmethod
    def onWin10orGreater():
        return False

    @staticmethod
    def isUnsupported():
        return True

class WindowsOldVideoGoodCards:
    @staticmethod
    def onWin10orGreater():
        return False

    @staticmethod
    def isUnsupported():
        return False

# These are the expected responses given the results above; for use in testing chosen results
mandatoryWin32 = {
    'required': True,
    'version': '4.0.1.310054',
    'channel': 'Second Life Release',
    'more_info': 'https://wiki.secondlife.com/wiki/Release_Notes/Second_Life_Release/4.0.1.310054',
    'platform': 'win32',
    'url': 'http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_i686_Setup.exe',
    'hash': '08f65e80c15aa5dd9cacc1465000032',
    'size': 52100032}

optionalWin32 = {
    'required': True,
    'version': '4.0.1.310054',
    'channel': 'Second Life Release',
    'more_info': 'https://wiki.secondlife.com/wiki/Release_Notes/Second_Life_Release/4.0.1.310054',
    'platform': 'win32',
    'url': 'http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_i686_Setup.exe',
    'hash': '08f65e80c15aa5dd9cacc1465000032',
    'size': 52100032}

mandatoryWin64 = {
    'required': True,
    'version': '4.0.1.310054',
    'channel': 'Second Life Release',
    'more_info': 'https://wiki.secondlife.com/wiki/Release_Notes/Second_Life_Release/4.0.1.310054',
    'platform': 'win64',
    'url': 'http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_x86_64_Setup.exe',
    'hash': '08f65e80c15aa5dd9cacc1465000064',
    'size': 52100064}

optionalWin64 = {
    'required': False,
    'version': '4.0.1.310054',
    'channel': 'Second Life Release',
    'more_info': 'https://wiki.secondlife.com/wiki/Release_Notes/Second_Life_Release/4.0.1.310054',
    'platform': 'win64',
    'url': 'http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_x86_64_Setup.exe',
    'hash': '08f65e80c15aa5dd9cacc1465000064',
    'size': 52100064}

optionalWinFallback = {
    'required': False,
    'version': '4.0.1.310054',
    'channel': 'Second Life Release',
    'more_info': 'https://wiki.secondlife.com/wiki/Release_Notes/Second_Life_Release/4.0.1.310054',
    'platform': 'win',
    'url': 'http://download.cloud.secondlife.com/FALLBACK/Second_Life_4_0_1_310054_x86_64_Setup.exe',
    'hash': '08f65e80c15aa5dd9cacc1465000f64',
    'size': 52100064}


class testChooseUpdate:

    def setup(self):
        os.environ['APP_DATA_DIR'] = os.path.dirname(os.path.abspath(__file__))
        BuildData.read()

    def test_equal_version_good_bitness(self):
        with patch( update_manager, "getBitness", bitness64 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoGoodCards ), \
             patch_dict(VVM_RESULT, 'required', True):

            BuildData.override('Version', VVM_RESULT['version'])

            chosen = update_manager.choose_update('win', {}, VVM_RESULT)

            assert_equal(chosen, {})

    def test_equal_version_wrong_bitness(self):
        with patch( update_manager, "getBitness", bitness32 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoGoodCards ):

            BuildData.override('Version', VVM_RESULT['version']) 

            chosen = update_manager.choose_update('win', {}, VVM_RESULT)

            assert_equal(chosen, mandatoryWin32)

    def test_win64_on_win32(self):
        with patch( update_manager, "getBitness", bitness32 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoGoodCards ):

            chosen = update_manager.choose_update('win', {}, VVM_RESULT)

            assert_equal(chosen, mandatoryWin32)

    def test_win32_on_win8_64(self):
        BuildData.override('Address Size', 32)
        with patch( update_manager, "getBitness", bitness64 ), \
             patch( update_manager, "WindowsVideo", WindowsOldVideoGoodCards ):

            chosen = update_manager.choose_update('win', {}, VVM_RESULT)

            assert_equal(chosen, mandatoryWin64)

    def test_win32_on_win10_64(self):
        BuildData.override('Address Size', 32)
        with patch( update_manager, "getBitness", bitness64 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoGoodCards ):

            chosen = update_manager.choose_update('win', {}, VVM_RESULT)

            assert_equal(chosen, mandatoryWin64)

    def test_win64_bad_cards(self):
        with patch( update_manager, "getBitness", bitness64 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoBadCards ):

            chosen = update_manager.choose_update('win', {}, VVM_RESULT)
            assert_equal(chosen, mandatoryWin32)

            with patch_dict(VVM_RESULT, 'required', True):
                chosen = update_manager.choose_update('win', {}, VVM_RESULT)
                assert_equal(chosen, mandatoryWin32)

    def test_win64_good_cards(self):
        with patch( update_manager, "getBitness", bitness64 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoGoodCards ): 
             
            chosen = update_manager.choose_update('win', {}, VVM_RESULT)
            assert_equal(chosen, optionalWin64)

    def test_win_only_bad_card_force_address_32(self):
        # Windows 10, bad video, force to 32
        with patch( update_manager, "getBitness", bitness64 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoBadCards ):
             
            chosen = update_manager.choose_update('win', force(32), VVM_RESULT)
            assert_equal(chosen, mandatoryWin32)

    def test_win_only_bad_card_force_address_64(self):
        # Windows 10, bad video, force to 64
        # This is the case in which getBitness() tries to force 'SkipBenchmark'
        # into Application.userpath()/user_settings/settings.xml. We'll have to
        # make a temporary one of those.
        with patch( update_manager, "getBitness", bitness64 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoBadCards ):
             
            chosen = update_manager.choose_update('win', force(64), VVM_RESULT)
            assert_equal(chosen, optionalWin64)
        
            with patch_dict(VVM_RESULT, 'required', True):
                chosen = update_manager.choose_update('win', force(64), VVM_RESULT)
                assert_equal(chosen, mandatoryWin64)

    def test_platform_fallback(self):
        with patch( update_manager, "getBitness", bitness64 ), \
             patch( update_manager, "WindowsVideo", Windows10VideoGoodCards ), \
             patch_dict(VVM_RESULT['platforms'], 'win64', DELETE):

            chosen = update_manager.choose_update('win', {}, VVM_RESULT)

            assert_equal(chosen, optionalWinFallback)
        
