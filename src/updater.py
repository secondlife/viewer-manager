#!/usr/bin/python
"""\
@file   updater.py
@author Nat Goodspeed
@date   2018-09-12
@brief  Query, download and install viewer updates as required.

$LicenseInfo:firstyear=2018&license=viewerlgpl$
Copyright (c) 2018, Linden Research, Inc.
$/LicenseInfo$
"""

import glob
import subprocess
import sys

class Error(Exception):
    pass

# called with the arguments we should pass to the viewer,
# the first of which is the viewer executable itself
def main(*args):
    # Happily, that means 'args' is already a suitable subprocess command.
    # Don't wait for the viewer to terminate, return immediately.
    subprocess.Popen(args)

if __name__ == "__main__":
    try:
        sys.exit(main(*sys.argv[1:]))
    except Error as err:
        sys.exit(str(err))
