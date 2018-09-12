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

import subprocess
import sys

class Error(Exception):
    pass

def main(viewer_executable):
    # don't wait for the viewer to terminate, return immediately
    subprocess.Popen([viewer_executable])

if __name__ == "__main__":
    try:
        sys.exit(main(*sys.argv[1:]))
    except Error as err:
        sys.exit(str(err))
