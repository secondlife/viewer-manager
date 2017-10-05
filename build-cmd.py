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
from shutil import copy, copytree, ignore_patterns, rmtree

import cgitb
import errno
import glob
import os
import os.path
import platform
import re
import subprocess
import sys
import trace

# so that we find the llbase installed by autobuild first
sys.path.insert(0,"packages/lib/python")
try:
    import llbase
except Exception as e:
    print "Python at %s could not find llbase" % sys.executable
    repr(e)
    sys.exit(1)
    
llbasedir = os.path.dirname(os.path.abspath(llbase.__file__))
print "Found llbase at: %r" % llbasedir

cgitb.enable(format='text')
darwin = re.compile('darwin')
linux = re.compile('linux')
windows = re.compile('win')
bit32 = re.compile('32 bit')

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
        print "sys.version: %s" % repr(sys.version)
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
    print "Python version string: %s" % sys.version
    print "Using python from: %s" % sys.executable
    autobuild = os.environ.get('AUTOBUILD')
    platform = getPlatform()

    # various places things go and come from.  
    print "sys.argv: %r" % sys.argv
    top = os.path.dirname(os.path.realpath(sys.argv[0]))
    stage = os.path.join(top, 'stage')
    stage_VMP = os.path.join(stage, "VMP")
    build = os.path.join(top, 'build')
    #if we decide we need to copy yet another directory tree, just add the source and dest to this dict
    # each value in iter_paths is a (src, dst) pair in that order
    src, dst = range(2)
    iter_paths = {'vmp': (os.path.join(top, 'vmp-src'), stage_VMP), 
                  'llb': (llbasedir, 'dst': os.path.join(stage_VMP, 'llbase'))
    }
    print "iterpaths: %r" % iter_paths
    icon = os.path.join(iter_paths['vmp'][src], 'icons', 'secondlife.ico')
    tests = os.path.join(iter_paths['vmp'][src],'tests')
    
    #We will ship a 32 bit VMP with 64 bit viewers
    if platform is None: 
        print >>sys.stderr, 'No valid platform found'
        sys.exit(1)         
    if platform == 'win64':
        #this is just a warning so that devs can build on w64 boxen
        print >>sys.stderr, 'The Windows VMP must be built on a 32-bit python Windows host'   
    
    #run nosetests
    # hardcoded fallback path
    if darwin.search(platform):
        nosetest_cmd = '/usr/local/bin/nosetests'
    elif linux.search(platform):
        nosetest_cmd = '/usr/bin/nosetests'
    else:
        nosetest_cmd = r"C:\Python27\Scripts\nosetests"
    # try various ways to find the command -- might just be on PATH
    for nosetests in "nosetests", os.environ.get('nosetests'), nosetest_cmd:
        # might not be a $nosetests environment variable
        if nosetests:
            try:
                subprocess.check_output([nosetests, "--version"])
            except OSError as err:
                # it's okay at this point if we don't find it
                if err.errno != errno.ENOENT:
                    # anything else, not okay
                    raise
            else:
                # yay, we succeeded in running nosetests, done searching
                break

    nose_env = os.environ.copy()
    nose_env['PYTHONPATH'] = ':'.join(sys.path)
    #stupid windows limit:
    # TypeError: encoded string too long (547, maximum length 519)
    #so nuke a few env vars we aren't using for this
    if platform == 'win32':
        nose_env['LIB'] = ""
        nose_env['WINDOWSSDK_EXECUTABLEPATH_X64'] = ''
        nose_env['PATH'] = llbasedir + ":" + nose_env['PATH']
        nose_env['PYTHONPATH'] = llbasedir

    try:
        print "About to call %s on %s from %s" % (nosetests, tests, iter_paths['vmp'][src])
        #print "nose environment: %r" % nose_env
        output = repr(subprocess.check_output([nosetests, tests],
                                              stderr=subprocess.STDOUT, env=nose_env,
                                              cwd=iter_paths['vmp'][src]))
    except subprocess.CalledProcessError as e:
        print repr(e)
        #these only exist if the exception is a CalledProcessError
        print "returncode: %s" % e.returncode
        print "command: %s" % e.cmd
        print "output: %s" % e.output
        sys.exit(1)
    except Exception as e:
        #more debug is best effort
        sys.exit(repr(e))

    output = output.replace('\\n','$')
    output = output.replace('\'','')
    output_list = output.split('$')
    one_line = ''
    for line in output_list:
        if 'Ran' in line or 'OK' in line:
            one_line =  one_line + " " + line
    print "Successful nosetest output:"
    print one_line
           
    #the version file consists of one line with the version string in it
    sourceVersionFile = os.path.join(top, "VERSION.txt")
    sourceVersion = open(sourceVersionFile, 'r').read().strip()
    packageVersionFile=open(os.path.join(stage,"VERSION.txt"), 'wb')
    packageVersionFile.write("%s.%s" % (sourceVersion, os.getenv('AUTOBUILD_BUILD_ID','0')))

    #copytree doesn't want the destination directory to pre-exist
    for srcdir, dstdir in iter_paths.values():
        if os.path.exists(dstdir):
            rmtree(dstdir, ignore_errors=True)
        copytree(srcdir, dstdir, ignore=ignore_patterns('*.pyc', '*tests*'))
        print "copied %s to %s with contents %s" % (srcdir, dstdir, repr(os.listdir(dstdir)))

    sourceLicenseFile = os.path.join(top, "LICENSE")
    copy(sourceLicenseFile, stage)
        
    #no else because we would have exited above
    if darwin.search(platform):
        pass
    elif linux.search(platform):
        #left as a separate clause in case lnx and mac ever diverge
        pass
    elif windows.search(platform):
        #to keep things as platform independent as possible, EXEs go into the same directory as .py files
        dstdir = iter_paths['vmp'][dst]
        # SL_Launcher is the main entry point for the VMP.
        # download_update is run as a separate process for background
        # downloads.
        vmp_files = [os.path.join(dstdir, f)
                     for f in ("SL_Launcher", "download_update.py")]
        print "Manifest of files to be compiled by pyinstaller: %s" % repr(vmp_files)

        #In a typical Windows install, pinstaller lives in C:\PythonXX\Scripts\pyinstaller.exe where Scripts is a sibling of the python executable
        #BUT that's not true of the virtualenv that autobuild runs in, so
        #search.
        pyinstaller = 'pyinstaller-script.py'
        try:
            # We want the FIRST path on $PATH containing pyinstaller. Before
            # generator comprehensions, we'd have written a list comprehension
            # and taken [0] of that -- but that would unconditionally check
            # every directory on $PATH. Writing next(generator) stops at the
            # first item to satisfy the filter, or raises StopIteration if no
            # item satisfies.
            pyinstaller_path = next(path for path in
                                    (os.path.join(dir, pyinstaller)
                                     for dir in os.environ["PATH"].split(os.pathsep))
                                    if os.path.exists(path))
        except StopIteration:
            # not on $PATH, hmm, try hard coding the canonical location
            pyinstaller_path = os.path.join(r'C:\Python27\Scripts', pyinstaller)
            if not os.path.exists(pyinstaller_path):
                sys.exit("pyinstaller not found")
            else:
                print "pyinstaller not on PATH, using hardcoded %r" % pyinstaller_path

        args = [ "-y", "-w", "-i", icon, "--clean", "--onefile", "--log-level", "DEBUG", "-p", dstdir, "--distpath", dstdir]
        # The requests module invokes the certifi.where function we provide
        # at _load_ time; since that module looks in the application data
        # directory to find build_data.json, it needs to find one, so point
        # to it with this override variable. This has no effect at run time
        # because the variable won't be defined.
        os.environ['APP_DATA_DIR'] = os.path.join(iter_paths['vmp'][src],'tests')
        for f in vmp_files:
            print "target %r exists: %s" % (f, os.path.exists(f))
            command = [sys.executable, pyinstaller_path] + args + [f]
            print "about to call %s " % command
            sys.stdout.flush()
            try:
                subprocess.check_call(command)
            except subprocess.CalledProcessError as e:
                print "Pyinstaller failed"
                print repr(e)
                print "returncode: %s" % e.returncode
                print "command: %s" % e.cmd
                print "output: %s" % e.output
                sys.exit(1)
            except Exception as e:
                sys.exit(repr(e))
        #best effort cleanup after pyinstaller
        rmtree(build, ignore_errors=True)
        for f in glob.glob(os.path.join(top, "*.spec")):
            try:
                os.remove(f)
            except:
                pass
    print "Build Succeeded"
        
if __name__ == '__main__':
    #trace is used as the pythonic equivalent of set -x in build_cmd.sh files, to produce output for TeamCity logs.
    libs = os.path.dirname(os.__file__)
    tracer = trace.Trace(ignoredirs=[sys.prefix, sys.exec_prefix, libs], ignoremods=["subprocess", "shutil"], trace=1, count=0, timing=False)
    tracer.run('main()')
