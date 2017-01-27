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

#autobuild itself needs llbase, so if python cannot find llbase,
#we are in a very weird state.
try:
    import llbase
except Exception as e:
    print "Python at %s could not find llbase" % sys.executable
    repr(e)
    sys.exit(1)

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
    autobuild = os.environ.get('AUTOBUILD')
    platform = getPlatform()

    # various places things go and come from.  
    top = os.path.dirname(os.path.realpath(sys.argv[0]))
    stage = os.path.join(top, 'stage')
    #if we decide we need to copy yet another directory tree, just add the source and dest to this dict
    iter_paths = {'vmp': {'src': os.path.join(top, 'vmp-src'), 'dst': os.path.join(stage, "VMP")}, 
                  'llb': {'src': os.path.dirname(llbase.__file__), 'dst': os.path.join(os.path.join(stage, "VMP"), 'llbase')}
    }
    tests = os.path.join(iter_paths['vmp']['src'],'tests')
    
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
        nosetest_cmd = "c:/Python27/Scripts/nosetests"
    os.chdir(iter_paths['vmp']['src'])
    try:
        print "About to call %s on %s from %s" % (nosetest_cmd, tests, iter_paths['vmp']['src'])
        subprocess.check_call([nosetest_cmd, tests])
    except Exception as e:
        print repr(e)
        print "returncode: %s" % e.returncode
        print "command: %s" % e.cmd
        print "output: %s" % e.output
        sys.exit(1)
    #remove dummy JSON file used during unit tests
    summary = os.path.join(iter_paths['vmp']['src'],'summary.json')
    if os.path.exists(summary):
        os.remove(summary)
    os.chdir(top)
           
    #the version file consists of one line with the version string in it
    sourceVersionFile = os.path.join(top, "VERSION.txt")
    print("%s: %s" % (sourceVersionFile, open(sourceVersionFile, 'r').read()))
    
    #copytree doesn't want the destination directory to pre-exist
    for key in iter_paths.keys():
        if os.path.exists(iter_paths[key]['dst']):
            rmtree(iter_paths[key]['dst'], ignore_errors=True)
        copytree(iter_paths[key]['src'], iter_paths[key]['dst'], ignore=ignore_patterns('*.pyc', '*tests*'))
        
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
        for f in os.listdir(iter_paths[key]['dst']):
            if p.search(f):
                vmp_files.append(str(os.path.join(iter_paths[key]['dst'], f)))
        #exe's for those that don't
        #In a typical Windows install, pyinstaller lives in C:\PythonXX\Scripts\pyinstaller.exe where Scripts is a sibling of the python executable
        #BUT that's not true of the virtualenv that autobuild runs in, so hard code the canonical location
        pyinstaller_exe = ['C:\Python27\Scripts\nosetests']
        args = [ "-y", "-windows", "--clean", "--onefile", "--log-level DEBUG", "-p " + iter_paths[key]['dst'], "--distpath " + iter_paths[key]['dst']]
        for f in vmp_files:
            try:
                target = []
                target.append(f)
                print "about to call %s using %s on %s" % (pyinstaller_exe, args, target)
                subprocess.check_call(pyinstaller_exe + args + target)
            except Exception as e:
                print "Pyinstaller failed"
                print repr(e)
                sys.exit(1)
        
if __name__ == '__main__':
    #trace is used as the pythonic equivalent of set -x in build_cmd.sh files, to produce output for TeamCity logs.
    tracer = trace.Trace(ignoredirs=[sys.prefix, sys.exec_prefix], ignoremods=["subprocess"], trace=1, count=0, timing=True)
    tracer.run('main()')
