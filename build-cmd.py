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

from __future__ import print_function

# Check https://wiki.lindenlab.com/wiki/How_To_Start_Using_Autobuild/Examples for info on how to build this package
from shutil import copy, copytree, ignore_patterns, rmtree

import cgitb
import errno
import glob
from importlib import import_module
import itertools
import os
import os.path
from platform import system
from pprint import pprint
import re
import subprocess
import sys
import trace

# set this up early to report crashes in anything that follows
cgitb.enable(format='text')

darwin  = re.compile('darwin')
linux   = re.compile('linux')
windows = re.compile('win')
bit32   = re.compile('32 bit')

# Python packages on which our build depends. Each entry maps a package name
# (the name you would 'import') to the string you would use to 'pip install'
# that package. That may include any version qualifiers, or whatever,
# recognized by pip.
BUILD_DEPS = dict(
    nose='nose',
    PyInstaller='pyinstaller',
)

# Python packages on which the VMP depends at runtime, in the same form.
RUNTIME_DEPS = dict(
    # TEMPORARY: We have an outstanding pull request to merge the eventlet
    # changes we need: https://github.com/eventlet/eventlet/pull/482
    # Until those get folded in upstream, though, we must name the specific
    # branch of the source repo for the pull request.
    # Per https://stackoverflow.com/a/24811490, although we should write:
    # git+https://github.com/nat-goodspeed/eventlet.git@ext-deps
    # the .zip form shown below is MUCH faster: e.g. 4 seconds versus 51.
    eventlet='https://github.com/nat-goodspeed/eventlet/archive/ext-deps.zip',
    llbase='llbase',
    requests='requests',
)

# As of 2018-03-30, these are the packages on which RUNTIME_DEPS depend. It
# bugs me (nat) to have to enumerate them explicitly -- but I have found no
# good way to derive only the set of modules imported by the packages above
# that are NOT in a vanilla macOS bundled Python install. ModuleFinder, for
# instance, presents *everything*, even the stuff bundled with the system.
# The code in main() derives the set of packages added to the current
# virtualenv as a consequence of pip installing the above, which should defend
# against the likely case of one or more of the above packages adding new non-
# default package dependencies.
# This list is used to ensure that even if one or more of the packages above
# are already present in the build host's system Python, and hence aren't
# added by pip install, we copy them anyway.
RUNTIME_DEPS_DEPS = [
    "certifi",
    "chardet",
    "dns",
    "enum",
    "greenlet",
    "idna",
    "monotonic",
    "six",
    "urllib3",
]

class Error(Exception):
    pass

#unify platform names and correctly return bitness
def getPlatform():
    plat = sys.platform.lower()
    bitness = '32'
    if sys.maxsize > 2**32:
        bitness = '64'
    if darwin.search(plat) is not None:
        return 'darwin' + bitness
    elif linux.search(plat):
        return 'linux' + bitness
    elif windows.search(plat):
        print("sys.version: %s" % repr(sys.version))
        #sadly, most of the ways that python uses to determine bitness
        #in the end rely on the CPU/memory bitness and all return 64
        #scraping sys.version is the only reliable method
        if bit32.search(sys.version):
            bitness = '32'
        else:
            bitness = '64'
        return 'win' + bitness
    else:
        return None
    
def main():
    print("Python version string: %s" % sys.version)
    print("Using python from: %s" % sys.executable)
    autobuild = os.environ.get('AUTOBUILD')
    platform = getPlatform()

    # various places things go and come from.  
    print("sys.argv: %r" % sys.argv)
    top, scriptname = os.path.split(os.path.realpath(sys.argv[0]))
    vmp_src = os.path.join(top, 'vmp-src')
    icon = os.path.join(vmp_src, 'icons', 'secondlife.ico')
    tests = os.path.join(vmp_src,'tests')
    stage = os.path.join(top, 'stage')
    stage_VMP = os.path.join(stage, "VMP")
    build = os.path.join(top, 'build')

    # ensure we're running in a virtualenv
    try:
        virtualenv = os.environ["VIRTUAL_ENV"]
    except KeyError:
        raise Error('Run %s within a virtualenv: it uses pip install' % scriptname)
    # iterating over a dict produces just its keys
    print("Installing %s into virtualenv: %s" %
          (', '.join(itertools.chain(BUILD_DEPS, RUNTIME_DEPS)), virtualenv))

    # First, install the stuff on which this build depends.
    # ...but only bother with pyinstaller on Windows
    if system() != 'Windows':
        BUILD_DEPS.pop("pyinstaller", None)

    try:
        run('pip', 'install', '-U', *BUILD_DEPS.values())
    except RunError as err:
        raise Error(str(err))

    # Try for a package we can assume to be present in any virtualenv. We
    # don't import this at the top of the script in case we're NOT in a
    # virtualenv and DON'T have setuptools available. In that case we should
    # hit the "Run within a virtualenv" test above, which will be more helpful
    # to the user than an ImportError regarding setuptools. (Huh?)
    import setuptools

    # Figure out in which directory this platform installs Python packages for
    # this virtualenv. We expect that every (modern) virtualenv contains a
    # setuptools install. Its __file__ is setuptools/__init__.pyc, so
    # dirname() gets us the setuptools directory, and joining that with pardir
    # should get us the containing directory.
    venvlibs = os.path.realpath(os.path.join(os.path.dirname(setuptools.__file__), os.pardir))
    if venvlibs.endswith(".egg"):
        # however, we've also found it nested under a setuptools-blah.egg directory
        venvlibs = os.path.realpath(os.path.join(venvlibs, os.pardir))
    print("%s installed into %s" % (', '.join(BUILD_DEPS), venvlibs))

    # Now that we know where our dependencies will be installed, take a
    # snapshot of what's there already (from the initial virtualenv setup plus
    # the above 'pip install').
    before = set(os.listdir(venvlibs))
##  print('\n'.join(itertools.chain(["inventory before runtime dependencies:"],
##                                  sorted(before))))

    # Now install the runtime stuff.
    # -U means: even if we already have an older version of (say) requests in
    # the system image, ensure our virtualenv has the version specified in
    # RUNTIME_DEPS (or the latest version if not version-locked).
    try:
        run('pip', 'install',
            # need this to process the eventlet dependency on a dnspython
            # version not yet available on PyPI
            '--process-dependency-links',
            '-U', *RUNTIME_DEPS.values())
    except RunError as err:
        raise Error(str(err))

    # We use copytree() to populate stage_VMP. copytree() doesn't like it when
    # its destination directory already exists.
    try:
        rmtree(stage_VMP, ignore_errors=True)
    except OSError as err:
        if err.errno != errno.ENOENT:
            # anything but "doesn't exist" is a problem
            raise

    # But make sure the stage directory exists
    try:
        os.makedirs(stage)
    except OSError as err:
        if err.errno != errno.EEXIST:
            raise

    #We ship a 32 bit VMP with 64 bit viewers
    if platform is None: 
        raise Error('No valid platform found')         
    if platform == 'win64':
        #this is just a warning so that devs can build on w64 boxen
        print('The Windows VMP must be built on a 32-bit python Windows host', sys.stderr)

    #run nosetests
    nose_env = os.environ.copy()
    #stupid windows limit:
    # TypeError: encoded string too long (547, maximum length 519)
    #so nuke a few env vars we aren't using for this
    if platform == 'win32':
        nose_env['LIB'] = ""
        nose_env['WINDOWSSDK_EXECUTABLEPATH_X64'] = ''

    # If we were to run nosetests installed in system Python, as opposed to
    # our virtualenv, then the scripts under test won't be able to import
    # (e.g.) eventlet -- which is only in our virtualenv, not system Python.
    # The tricky thing is that if system Python already contains an up-to-date
    # version of nose, 'pip install -U nose' won't actually write anything to
    # our virtualenv.
    # So instead, invoke nosetests using the alternate tactic in which we
    # explicitly run python, the one from our virtualenv, explicitly passing
    # the nose.core module pathname:
    # http://nose.readthedocs.io/en/latest/usage.html
    # Defer importing nose to this point in case we DID pip install it.
    import nose.core
    command = [sys.executable, nose.core.__file__, tests]
    print("About to call %s\n"
          "from %s" % (command, vmp_src))
    try:
        #print("nose environment: %r" % nose_env)
        output = subprocess.check_output(command,
                                         stderr=subprocess.STDOUT, env=nose_env,
                                         cwd=vmp_src)
    except subprocess.CalledProcessError as e:
        #exception attribute only exists on CalledProcessError
        raise Error("Tests failed: %s\n"
                    "output:\n%s" % (e, e.output))
    except Exception as e:
        #more debug is best effort
        raise Error("%s didn't run: %s: %s" % (command, e.__class__.__name__, e))

    print("Successful nosetest output:")
    print(' '.join(line for line in output.splitlines()
                   if 'Ran' in line or 'OK' in line))
           
    #the version file consists of one line with the version string in it
    sourceVersionFile = os.path.join(top, "VERSION.txt")
    with open(sourceVersionFile, 'r') as svf:
        sourceVersion = svf.read().strip()
    with open(os.path.join(stage,"VERSION.txt"), 'w') as packageVersionFile:
        packageVersionFile.write("%s.%s" % (sourceVersion, os.getenv('AUTOBUILD_BUILD_ID','0')))

    sourceLicenseFile = os.path.join(top, "LICENSE")
    copy(sourceLicenseFile, stage)

    # -------------------------------- Posix ---------------------------------
    if darwin.search(platform) \
    or linux.search(platform):
        # Having installed our dependencies and -- importantly -- all THEIR
        # dependencies, figure out what we added.
        after = set(os.listdir(venvlibs))
    ##  print('\n'.join(itertools.chain(["inventory after installing runtime dependencies:"],
    ##                                  sorted(after))))
        installed = after - before
        print('\n'.join(itertools.chain(["newly-installed runtime dependencies:"],
                                        sorted(installed))))
        # As of 2018-03-27, anyway, there's some cruft in that directory
        tocopy = set(os.path.join(venvlibs, f)
                     for f in installed
                     if not (f.endswith(".dist-info") or f.endswith(".egg-info")))
        # The steps above intentionally capture only stuff added by our 'pip
        # install' command. But what if one or more of our dependencies was
        # already present in system Python before we created the virtualenv? In
        # that case, it wouldn't show up in 'installed' or 'tocopy'. Stir in the
        # set we started with, plus (what we believe to be) their dependencies,
        # converting from package name to file or directory name.
        for pkg in itertools.chain(RUNTIME_DEPS, RUNTIME_DEPS_DEPS):
            try:
                modfile = import_module(pkg).__file__
            except ImportError as err:
                # This may mean that one of RUNTIME_DEPS_DEPS is no longer
                # required by any of RUNTIME_DEPS, and hence was not installed.
                # A developer should remove that item from RUNTIME_DEPS_DEPS, but
                # we shouldn't fail the build for that reason.
                # Produce a warning to stderr, but keep going.
                print("%s: %s" % (err.__class__.__name__, err), file=sys.stderr)
            else:
                # splitext()[0] strips off the extension (e.g. .pyc)
                # split() takes apart the directory path from the simple name
                moddir, modname = os.path.split(os.path.splitext(modfile)[0])
                if modname == '__init__':
                    # If an imported module's name is __init__, the name
                    # represents a whole package. Have to copy its entire
                    # directory.
                    tocopy.add(moddir)
                else:
                    # imported module isn't named __init__, therefore it's a
                    # single file module -- copy just that file
                    tocopy.add(modfile)
        print('\n'.join(itertools.chain(["packages to copy:"],
                                        sorted(tocopy))))

        ignores = ignore_patterns('*.pyc', '*tests*')
        # start with the parent directory
        copytree(vmp_src, stage_VMP, ignore=ignores)
        # Copy packages installed by RUNTIME_DEPS.
        for srcpath in tocopy:
            dstpath = os.path.join(stage_VMP, os.path.basename(srcpath))
            print("Copying %s to %s" % (srcpath, dstpath))
            if os.path.isdir(srcpath):
                # srcpath represents a whole package. Have to copy its entire
                # directory.
                copytree(srcpath, dstpath, ignore=ignores)
            else:
                # it's a single file module -- copy just that file
                copy(srcpath, dstpath)
    # ------------------------------- Windows --------------------------------
    elif windows.search(platform):
        #In a typical Windows install, pinstaller lives in C:\PythonXX\Scripts\pyinstaller.exe where Scripts is a sibling of the python executable
        #BUT that's not true of the virtualenv that autobuild runs in, so
        #search.
        pyinstaller_runners = [
            # If what we find is pyinstaller-script.py, need to run it with
            # our own interpreter.
            [sys.executable, 'pyinstaller-script.py'],
            # On the other hand, if we find pyinstaller.exe, just run that.
            ['pyinstaller.exe'],
            ]
        # search directories on PATH
        # use one-off exception to escape doubly-nested loop
        class Found(Exception):
            pass
        try:
            for dir in os.environ["PATH"].split(os.pathsep):
                for cmd in pyinstaller_runners:
                    # Check if the LAST entry in pyinstaller_cmd is in this dir.
                    pyinstaller_path = os.path.join(dir, cmd[-1])
                    if os.path.exists(pyinstaller_path):
                        raise Found()
        except Found:
            pass
        else:
            # not on $PATH, hmm, try hard coding the canonical location
            dir = r'C:\Python27\Scripts'
            cmd = pyinstaller_runners[0]
            pyinstaller_path = os.path.join(dir, cmd[-1])
            print("pyinstaller not on PATH, trying hardcoded %s" % pyinstaller_path)

        # take everything but the last entry in cmd, then append
        # the new (prepended with dir) pyinstaller_path as last
        pyinstaller_cmd = cmd[:-1] + [pyinstaller_path]

        os.mkdir(stage_VMP)

        # SL_Launcher is the main entry point for the VMP.
        pyinstaller(pyinstaller_cmd,
                    mainfile=os.path.join(vmp_src, "SL_Launcher"),
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

def pyinstaller(pyinstaller_cmd, mainfile, dstdir, icon, manifest_from_build=None):
    basename = os.path.basename(mainfile)
    print((" %s " % basename).center(72, '='))
    print("target %r exists: %s" % (mainfile, os.path.exists(mainfile)))
    # https://pyinstaller.readthedocs.io/en/stable/usage.html#options
    command = pyinstaller_cmd + [
        # don't prompt, just overwrite previous exe
        "-y",
        # suppress opening console window at runtime
        "-w",
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

    # Temporary: until hook-eventlet.support.greendns.py makes it into
    # PyInstaller, use the one in this directory.
    command.append('--additional-hooks-dir=' + os.path.dirname(__file__))
    try:
        run(*command)
    except Exception as e:
        raise Error("Error building %s: %s: %s" % (mainfile, e.__class__.__name__, e))

    if manifest_from_build:
        basebase = os.path.splitext(basename)[0]
        exe = os.path.join(dstdir, basebase + ".exe")
        manifest = os.path.join(manifest_from_build, basebase, basebase + '.exe.manifest')
        # https://msdn.microsoft.com/en-us/library/ms235591.aspx
        try:
            run('mt.exe', '-manifest', manifest, '-outputresource:%s;1' % exe)
        except RunError as e:
            raise Error("Couldn't embed manifest %s in %s: %s" % (manifest, exe, e))

# We don't bother to catch CalledProcessError and reraise it as RunError; we
# just alias the original exception.
RunError = subprocess.CalledProcessError

def run(*command, **kwds):
    print(' '.join((("'%s'" % word) if ' ' in word else word)
                   for word in command))
    sys.stdout.flush()
    # it's caller's responsibility to catch RunError
    return subprocess.check_call(command, **kwds)

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
