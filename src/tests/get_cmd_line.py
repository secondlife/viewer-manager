#!/usr/bin/env python3
"""\
@file   get_cmd_line.py
@author Nat Goodspeed
@date   2022-01-28
@brief  Capture the get_cmd_line() function from old SL_Launcher.

This function is no longer used by production code, but it's still used in
tests.

$LicenseInfo:firstyear=2022&license=viewerlgpl$
Copyright (c) 2022, Linden Research, Inc.
$/LicenseInfo$
"""

from llbase import llsd
import os
from util import pass_logger, Application

@pass_logger
def get_cmd_line(log, cmd_settings_file = None):
    if cmd_settings_file is None:
        cmd_settings_file = os.path.join(Application.app_data_path(),
                                         'app_settings', 'cmd_line.xml')

    log.debug("reading command line rules from '%s'" % cmd_settings_file)
    try:
        cmd_line = llsd.parse(open(cmd_settings_file, 'rb').read())
    except (IOError, OSError, llsd.LLSDParseError) as err:
        log.warning("Could not parse settings file %r: %r", cmd_settings_file, err)
        cmd_line = {}

    return cmd_line
