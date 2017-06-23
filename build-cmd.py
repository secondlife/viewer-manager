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
    python_native = os.environ.get('PYTHON_COMMAND_NATIVE')
    print "Using python from: %s" % python_native
    autobuild = os.environ.get('AUTOBUILD')
    platform = getPlatform()

    # various places things go and come from.  
    print "sys.argv: %r" % sys.argv
    top = os.path.dirname(os.path.realpath(sys.argv[0]))
    stage = os.path.join(top, 'stage')
    build = os.path.join(top, 'build')
    #if we decide we need to copy yet another directory tree, just add the source and dest to this dict
    iter_paths = {'vmp': {'src': os.path.join(top, 'vmp-src'), 'dst': os.path.join(stage, "VMP")}, 
                  'llb': {'src': llbasedir, 'dst': os.path.join(os.path.join(stage, "VMP"), 'llbase')}
    }
    print "iterpaths: %r" % iter_paths
    icon = os.path.join(iter_paths['vmp']['src'], 'icons', 'secondlife.ico')
    tests = os.path.join(iter_paths['vmp']['src'],'tests')
    
    #We will ship a 32 bit VMP with 64 bit viewers
    if platform is None: 
        print >>sys.stderr, 'No valid platform found'
        sys.exit(1)         
    if platform == 'win64':
        print >>sys.stderr, 'The Windows VMP must be built on a 32-bit python Windows host'
        sys.exit(1)    
    
    #run nosetests
    if 'nosetests' in os.environ:
        nosetest_cmd = os.environ['nosetests']
    elif darwin.search(platform):
        nosetest_cmd = '/usr/local/bin/nosetests'
    elif linux.search(platform):
        nosetest_cmd = '/usr/bin/nosetests'
    else:
        nosetest_cmd = r"C:\Python27\Scripts\nosetests"
        
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

    os.chdir(iter_paths['vmp']['src'])
    try:
        print "About to call %s on %s from %s" % (nosetest_cmd, tests, iter_paths['vmp']['src'])
        #print "nose environment: %r" % nose_env
        output = repr(subprocess.check_output([nosetest_cmd, tests], stderr=subprocess.STDOUT, env=nose_env))
    except Exception as e:
        print repr(e)
        try:
            #these only exist if the exception is a CalledProcessError
            print "returncode: %s" % e.returncode
            print "command: %s" % e.cmd
            print "output: %s" % e.output
        except:
            #more debug is best effort
            pass
        sys.exit(1)
    
    output = output.replace('\\n','$')
    output = output.replace('\'','')
    output_list = output.split('$')
    one_line = ''
    for line in output_list:
        if 'Ran' in line or 'OK' in line:
            one_line =  one_line + " " + line
    print "Successful nosetest output:"
    print one_line
    os.chdir(top)
           
    #the version file consists of one line with the version string in it
    sourceVersionFile = os.path.join(top, "VERSION.txt")
    sourceVersion = open(sourceVersionFile, 'r').read().strip()
    packageVersionFile=open(os.path.join(stage,"VERSION.txt"), 'wb')
    packageVersionFile.write("%s.%s" % (sourceVersion, os.getenv('AUTOBUILD_BUILD_ID','0')))

    #copytree doesn't want the destination directory to pre-exist
    for key in iter_paths.keys():
        if os.path.exists(iter_paths[key]['dst']):
            rmtree(iter_paths[key]['dst'], ignore_errors=True)
        copytree(iter_paths[key]['src'], iter_paths[key]['dst'], ignore=ignore_patterns('*.pyc', '*tests*'))
        print "copied %s to %s with contents %s" % (iter_paths[key]['src'], iter_paths[key]['dst'], repr(os.listdir(iter_paths[key]['dst'])))

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
        p = re.compile(r"\.py$")
        vmp_files = []
        for f in os.listdir(iter_paths[key]['dst']):
            if p.search(f):
                vmp_files.append(str(os.path.join(iter_paths[key]['dst'], f)))
        #the only non-py file to be compiled.
        vmp_files.append(str(os.path.join(iter_paths[key]['dst'], 'SL_Launcher')))
        print "Manifest of files to be compiled by pyinstaller: %s" % repr(vmp_files)
        #In a typical Windows install, pinstaller lives in C:\PythonXX\Scripts\pyinstaller.exe where Scripts is a sibling of the python executable
        #BUT that's not true of the virtualenv that autobuild runs in, so hard code the canonical location
        pyinstaller_exe = [r'C:\Python27\Scripts\pyinstaller-script.py']
        args = [ "-y", "-w", "-i", icon, "--clean", "--onefile", "--log-level", "DEBUG", "-p", iter_paths[key]['dst'], "--distpath", iter_paths[key]['dst']]
        print "pyinstaller exists: %s" % os.path.exists(pyinstaller_exe[0])
        if not os.path.exists(pyinstaller_exe[0]):
            sys.exit(1)
        # The requests module invokes the certifi.where function we provide
        # at _load_ time; since that module looks in the application data
        # directory to find build_data.json, it needs to find one, so point
        # to it with this override variable. This has no effect at run time
        # because the variable won't be defined.
        os.environ['APP_DATA_DIR'] = os.path.join(top,'vmp-src','tests')
        for f in vmp_files:
            try:
                target = []
                target.append(f)
                print "target exists: %s" % os.path.exists(target[0])
                print "about to call %s " % ([python_native] + pyinstaller_exe + args + target)
                subprocess.check_output([python_native] + pyinstaller_exe + args + target)
            except Exception as e:
                print "Pyinstaller failed"
                print repr(e)
                try:
                    print "returncode: %s" % e.returncode
                    print "command: %s" % e.cmd
                    print "output: %s" % e.output
                except:
                    pass
                sys.exit(1)
        #best effort cleanup after pyinstaller
        rmtree(build, ignore_errors=True)
        for f in os.listdir(top):
            if f.endswith('spec'):
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
