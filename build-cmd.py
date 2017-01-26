#!/usr/bin/env python


# Check https://wiki.lindenlab.com/wiki/How_To_Start_Using_Autobuild/Examples for info on how to build this package
from shutil import copy, copytree, ignore_patterns, rmtree

import cgitb
import os
import os.path
import re
import subprocess
import sys
import trace

cgitb.enable(format='text')
darwin = re.compile('darwin')
linux = re.compile('linux')
windows = re.compile('win')

#unify platform names and correctly return bitness
def getPlatform():
    platform = sys.platform.lower()
    bitness = '32'
    if sys.maxsize > 2**32:
        bitness = '64'
    if darwin.search(platform) is not None:
        return 'darwin' + bitness
    elif linux.search(platform):
        return 'linux' + bitness
    elif windows.search(platform):
        return 'win' + bitness
    else:
        return None
    

def main():
    if os.environ['AUTOBUILD'] is None:
        sys.exit(1)
    autobuild = os.environ['AUTOBUILD']
    top = os.path.dirname(os.path.realpath(sys.argv[0]))
    stage = os.path.join(top, "stage")
    src = os.path.join(top, 'vmp-src')
    dst = os.path.join(stage, "VMP")    
    tests = os.path.join(src,'tests')
    platform = getPlatform()
    #We will ship a 32 bit VMP with 64 bit viewers
    if platform is None: 
        print >>sys.stderr, 'No valid platform found'
        sys.exit(1)         
    if platform == 'win64':
        print >>sys.stderr, 'The Windows VMP must be built on a 32-bit Windows host'
        sys.exit(1)    
    
    
    #run nosetests
    if darwin.search(platform):
        nosetest_cmd = '/usr/local/bin/nosetests'
    elif linux.search(platform):
        nosetest_cmd = '/usr/bin/nosetests'
    else:
        nosetest_cmd = 'TBD WOLF-688'
    os.chdir(src)
    try:
        print "About to call %s on %s from %s" % (src, nosetest_cmd, tests)
        subprocess.check_call([nosetest_cmd, tests])
    except Exception as e:
        print repr(e)
        sys.exit(1)
    #remove dummy JSON file used during unit tests
    summary = os.path.join(src,'summary.json')
    if os.path.exists(summary):
        os.remove(summary)
    os.chdir(top)
    
           
    #the version file consists of one line with the version string in it
    sourceVersionFile = os.path.join(top, "VERSION.txt")
    print("%s: %s" % (sourceVersionFile, open(sourceVersionFile, 'r').read()))
    
    #copytree doesn't want the directory to pre-exist
    if os.path.exists(dst):
        rmtree(dst, ignore_errors=True)
        
    #all three platforms do this
    #python for those that have, also for libary access for pyinstaller and list of files to compile
    copytree(src, dst, ignore=ignore_patterns('*.pyc', '*tests*'))
    copy(sourceVersionFile, stage)
        
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
        for f in os.listdir(dest):
            if p.search(f):
                vmp_files.append(str(os.path.join(dest, f)))
        #exe's for those that don't
        #In a typical Windows install, pyinstaller lives in C:\PythonXX\Scripts\pyinstaller.exe where Scripts is a sibling of the python executable
        pyinstaller_exe = os.path.join(os.path.dirname(sys.executable), 'Scripts/pyinstaller.exe')
        args = [ "-y", "-windows", "--clean", "--onefile", "--log-level DEBUG", "-p " + dest, "--distpath " + dest]
        for f in vmp_files:
            try:
                target = []
                target.append(f)
                subprocess.check_call(pyinstaller_exe + args + target)
            except Exception as e:
                print "Pyinstaller failed"
                print repr(e)
                sys.exit(1)
        

if __name__ == '__main__':
    #trace is used as the pythonic equivalent of set -x in build_cmd.sh files, to produce output for TeamCity logs.
    tracer = trace.Trace(ignoredirs=[sys.prefix, sys.exec_prefix], ignoremods=["subprocess"], trace=1, count=0, timing=True)
    tracer.run('main()')
