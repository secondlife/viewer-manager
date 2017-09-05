#!/usr/bin/env python

"""\
@file   test_update_manager_convert_version_file_style.py
@author coyot
@date   2016-06-01

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
import shutil
import tempfile
import update_manager
from vmp_util import skip_settings, write_settings
from patch import patch, patch_dict

def test_linux():
    bitness = update_manager.getBitness('lnx', settings={})
    assert_equal(bitness, 64)

def test_mac():
    bitness = update_manager.getBitness('mac', settings={})
    assert_equal(bitness, 64)

def test_win():
    if 'PROGRAMFILES(X86)' in os.environ:
        bitness = 64
    else:
        bitness = 32
    assert_equal(bitness, update_manager.getBitness('win', settings={}))
    
def test_win_no_bad_card():
    # For the duration, pretend we're running 64-bit Windows.
    # This string literal is actual observed wmic output on a Windows 7
    # machine. No idea why it uses '\r\r\n' as end-of-line. <eyeroll/>
    with patch_dict(os.environ, 'PROGRAMFILES(X86)', 'nonempty'), \
         patch(update_manager, "wmic",
               lambda *args:
               'Name                    \r\r\n'
               'NVIDIA GeForce GTS 450  \r\r\n'
               '\r\r\n'):
       assert_equal(update_manager.getBitness('win', settings={}), 64)

def test_win_bad_and_good_cards():
    with patch_dict(os.environ, 'PROGRAMFILES(X86)', 'nonempty'):
        with patch(update_manager, "wmic",
                   lambda *args:
                   'Name                    \r\r\n'
                   'Intel(R) HD Graphics    \r\r\n'
                   'NVIDIA GeForce GTS 450  \r\r\n'
                   '\r\r\n'):
           assert_equal(update_manager.getBitness('win', settings={}), 64)

        # relative order SHOULD NOT MATTER
        with patch(update_manager, "wmic",
                   lambda *args:
                   'Name                    \r\r\n'
                   'NVIDIA GeForce GTS 450  \r\r\n'
                   'Intel(R) HD Graphics 2000 \r\r\n'
                   '\r\r\n'):
           assert_equal(update_manager.getBitness('win', settings={}), 64)

        with patch(update_manager, "wmic",
                   lambda *args:
                   'Name                    \r\r\n'
                   'Intel(R) HD Graphics 3000 \r\r\n'
                   'Intel(R) HD Graphics 5000 \r\r\n' # not (currently!) in bad list
                   '\r\r\n'):
           assert_equal(update_manager.getBitness('win', settings={}), 64)

def test_win_only_bad_card():
    with patch_dict(os.environ, 'PROGRAMFILES(X86)', 'nonempty'), \
         patch(update_manager, "wmic",
               lambda *args:
               'Name                    \r\r\n'
               'Intel(R) HD Graphics 2500 \r\r\n'
               '\r\r\n'):
       assert_equal(update_manager.getBitness('win', settings={}), 32)

def test_win_only_bad_cards():
    with patch_dict(os.environ, 'PROGRAMFILES(X86)', 'nonempty'), \
         patch(update_manager, "wmic",
               lambda *args:
               'Name                    \r\r\n'
               'Intel(R) HD Graphics 3000 \r\r\n'
               'Intel(R) HD Graphics 4000 \r\r\n'
               '\r\r\n'):
       assert_equal(update_manager.getBitness('win', settings={}), 32)

def test_win_only_bad_card_force_address_32():
    with patch_dict(os.environ, 'PROGRAMFILES(X86)', 'nonempty'), \
         patch(update_manager, "wmic",
               lambda *args:
               'Name                    \r\r\n'
               'Intel(R) HD Graphics 2500 \r\r\n'
               '\r\r\n'):
       assert_equal(update_manager.getBitness('win',
                                              settings=dict(ForceAddressSize='32')),
                    32)

class DummyApplication(object):
    def __init__(self, path):
        self.path = path

    def userpath(self):
        return self.path

    def user_settings_path(self):
        return os.path.join(self.path, 'user_settings', 'settings.xml')

def test_win_only_bad_card_force_address_64():
    # This is the case in which getBitness() tries to force 'SkipBenchmark'
    # into Application.userpath()/user_settings/settings.xml. We'll have to
    # make a temporary one of those.
    tempdir = tempfile.mkdtemp()
    try:
        Application = DummyApplication(tempdir)
        settings_path = Application.user_settings_path()

        # ensure Application.userpath() returns our tempdir
        with patch_dict(os.environ, 'PROGRAMFILES(X86)', 'nonempty'), \
             patch(update_manager, "Application", Application), \
             patch(update_manager, "wmic",
                   lambda *args:
                   'Name                    \r\r\n'
                   'Intel(R) HD Graphics 2500 \r\r\n'
                   '\r\r\n'):

            # no settings file at first
            assert_equal(update_manager.getBitness('win',
                                                   settings=dict(ForceAddressSize='64')),
                         64)

            # settings file should have been created with that one entry
            assert_equal(update_manager.get_settings(settings_path), skip_settings)

            # overwrite that settings file with an empty one
            write_settings(settings_object={}, settings_path=settings_path)

            assert_equal(update_manager.getBitness('win',
                                                   settings=dict(ForceAddressSize='64')),
                         64)

            # settings file should have been rewritten with that one entry
            assert_equal(update_manager.get_settings(settings_path), skip_settings)

            # now put a non-empty settings file
            write_settings(settings_object=dict(ForceAddressSize='64'),
                           settings_path=settings_path)

            assert_equal(update_manager.getBitness('win',
                                                   settings=dict(ForceAddressSize='64')),
                         64)

            # should have preserved the existing entries, while adding SkipBenchmark
            settings = update_manager.get_settings(settings_path)
            assert_equal(settings["ForceAddressSize"], "64")
            assert_equal(settings["SkipBenchmark"], skip_settings["SkipBenchmark"])

    finally:
        # clean up modified settings file when done
        shutil.rmtree(tempdir)
