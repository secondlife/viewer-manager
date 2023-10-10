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


# Check https://wiki.lindenlab.com/wiki/How_To_Start_Using_Autobuild/Examples for info on how to build this package
from shutil import copy, rmtree

from collections import deque
from contextlib import suppress
import errno
import glob
from importlib import import_module
import itertools
import os
import os.path
from platform import system
from pprint import pprint
import re
import shlex
import subprocess
import sys
import struct
import trace

# set this up early to report crashes in anything that follows
try:
    import cgitb
    cgitb.enable(format='text')
except ImportError:
    # sigh, they should not have deprecated and removed this
    pass

class Error(Exception):
    pass
    
def main():
    print("Python version string: %s" % sys.version)
    print("Using python from: %s" % sys.executable)
    autobuild = os.environ.get('AUTOBUILD')

    # various places things go and come from.  
    print("sys.argv: %r" % sys.argv)
    top, scriptname = os.path.split(os.path.realpath(sys.argv[0]))
    src = os.path.join(top, 'src')
    icon = os.path.join(src, 'icons', 'secondlife.ico')
    tests = os.path.join(src,'tests')
    stage = os.path.join(top, 'stage')
    stage_VMP = os.path.join(stage, "VMP")
    build = os.path.join(top, 'build')

    # Make sure our staging area is clean because our manifest sweeps up
    # whatever's in this directory.
    with suppress(FileNotFoundError):
        rmtree(stage_VMP, ignore_errors=True)

    # But make sure the stage directory exists
    with suppress(FileExistsError):
        os.makedirs(stage)

    # Invoke pytest using the alternate tactic in which we explicitly run
    # python, our own interpreter, explicitly invoking the pytest module:
    # https://docs.pytest.org/en/latest/how-to/usage.html#calling-pytest-through-python-m-pytest
    command = [sys.executable, '-m', 'pytest', tests]
    print("About to call %s\n"
          "from %s" % (command, src))
    try:
        output = subprocess.check_call(command, cwd=src)
    except subprocess.CalledProcessError as e:
        raise Error("Tests failed: %s" % e) from e
    except Exception as e:
        #more debug is best effort
        raise Error("%s didn't run: %s: %s" % (command, type(e).__name__, e)) from e
           
    #the version file consists of one line with the version string in it
    sourceVersionFile = os.path.join(top, "VERSION.txt")
    with open(sourceVersionFile, 'r') as svf:
        sourceVersion = svf.read().strip()
    with open(os.path.join(stage,"VERSION.txt"), 'w') as packageVersionFile:
        packageVersionFile.write("%s-%s" % (sourceVersion, os.getenv('AUTOBUILD_BUILD_ID','0')))

    sourceLicenseFile = os.path.join(top, "LICENSE")
    copy(sourceLicenseFile, stage)

    # Now that we're using Python 3, we can't assume that's the default Python
    # on every target system -- so we must use PyInstaller on all platforms.
    os.mkdir(stage_VMP)
    pyinstaller(mainfile=os.path.join(src, "SLVersionChecker.py"),
                dstdir=stage_VMP,
                icon=icon)

    #best effort cleanup after pyinstaller
    rmtree(build, ignore_errors=True)
    for f in glob.glob(os.path.join(top, "*.spec")):
        try:
            os.remove(f)
        except:
            pass

    print("Build Succeeded")

def pyinstaller(mainfile, dstdir, icon, manifest_from_build=None):
    basename = os.path.basename(mainfile)
    print((" %s " % basename).center(72, '='))
    print("target %r exists: %s" % (mainfile, os.path.exists(mainfile)))
    # https://pyinstaller.readthedocs.io/en/stable/usage.html#options
    command = [
        # don't prompt, just overwrite previous exe
        "-y",
        # icon to use for the generated executable
        "-i", icon,
        # don't reuse previous PyInstaller cache
        "--clean",
        # cram everything into single .exe file
        "--onefile",
        # control build-time output detail (for TeamCity builds)
        "--log-level", "DEBUG",
        # search specified path for Python imports
        "-p", dstdir,
        # where to put the generated executable
        "--distpath", dstdir,
        mainfile]
    # Also note, in case of need:
    # --debug: produce runtime startup messages about imports and such (may
    #          need --console rather than -w?)
    if system() == 'Windows':
        # suppress opening console window at runtime
        command.insert(0, "-w")

    # Temporary: until hook-eventlet.support.greendns.py makes it into
    # PyInstaller, use the one in this directory.
    command.append('--additional-hooks-dir=' + os.path.dirname(__file__))

    # https://pyinstaller.readthedocs.io/en/stable/usage.html#running-pyinstaller-from-python-code
    import PyInstaller.__main__
    print_command(PyInstaller.__main__.__file__, *command)
    try:
        PyInstaller.__main__.run(command)
    except Exception as e:
        raise Error("Error building %s: %s: %s" % (mainfile, e.__class__.__name__, e)) from e

    if system() == 'Windows' and manifest_from_build:
        basebase = os.path.splitext(basename)[0]
        exe = os.path.join(dstdir, basebase + ".exe")
        manifest = os.path.join(manifest_from_build, basebase, basebase + '.exe.manifest')
        # https://msdn.microsoft.com/en-us/library/ms235591.aspx
        try:
            subprocess.check_call(
                ['mt.exe', '-manifest', manifest, '-outputresource:%s;1' % exe])
        except subprocess.CalledProcessError as e:
            raise Error("Couldn't embed manifest %s in %s: %s" % (manifest, exe, e)) from e

def print_command(*command):
    print(' '.join(shlex.quote(word) for word in command), flush=True)

if __name__ == '__main__':
    #trace is used as the pythonic equivalent of set -x in build_cmd.sh files, to produce output for TeamCity logs.
    libs = os.path.dirname(trace.__file__)
    tracer = trace.Trace(ignoredirs=[sys.prefix, sys.exec_prefix, libs],
                         trace=1, count=0, timing=False)
    try:
##      tracer.run('main()')
        main()
    except Error as err:
        sys.exit(str(err))
