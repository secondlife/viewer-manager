#!/usr/bin/env python

from __future__ import print_function

"""\
$LicenseInfo:firstyear=2006&license=viewerlgpl$
Second Life Viewer Source Code
Copyright (C) 2006-2014, Linden Research, Inc.

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

"""
@file   SL_Launcher.py
@author coyot
@date   2016-06-23
"""

from functools import partial
import os
import os.path
import platform
import subprocess
import sys

# Must be FIRST VMP IMPORT: in case of crash anywhere along the way, try to
# ensure that at least we'll produce diagnostic output into the log.
from util import pass_logger, SL_Logging, Application, BuildData, udir, ufile, subprocess_args
if __name__ == "__main__":
    # sets up unhandled exception handler in sys.excepthook
    # do this right away because in the past we've hit crashes even importing
    # other VMP modules
    SL_Logging.getLogger('SL_Launcher')
    # Any print output from anything along the way should also be logged.
    sys.stdout = SL_Logging.stream()
    sys.stderr = sys.stdout

import eventlet

if __name__ == "__main__":
    # We use a number of other modules, including 'requests'. We want every
    # single module that performs network I/O, or other conventional
    # operations, to perform it using eventlet magic.
    # On Posix, we must pass os=True.
    # On Windows, we must NOT pass os=True.  :-P
    # https://github.com/eventlet/eventlet/issues/483
    eventlet.monkey_patch(os=(platform.system() != 'Windows'),
                          select=True, socket=True, time=True,
                          builtins=True, subprocess=True)

from runner import PopenRunner
from InstallerUserMessage import status_message, root
from tkeventlet import TkGreenthread

#if for some reason we are running on a POSIX machine with python less than 2.7
#just give up on VMP and execute the viewer per product.
def python_version_check():
    if platform.system() != 'Windows' and platform.python_version_tuple() < (2, 7, 0):
        log = SL_Logging.getLogger('SL_Launcher')
        log.error("Computer is below minimum specifications. Python version needs to be 2.7, but is %r" % platform.python_version())
        absfile = os.path.abspath(ufile(__file__))
        if platform.system == 'Darwin':
            import glob
            executable_name = "Second Life"
            # __file__ is
            # Second Life.app/Contents/Resources/launcher.app/Contents/MacOS/SL_Launcher.py
            # need to run
            # Second Life.app/Contents/Resources/viewer.app/Contents/MacOS/executable_name
            # but we don't know the exact name of either launcher.app or
            # viewer.app, just that they should (!) be the only two .apps
            pieces = absfile.rsplit(os.sep, 4)
            try:
                pattern = os.path.join(pieces[-5], "*.app")
            except IndexError:
                log.error("Can't locate viewer relative to %s", absfile)
                sys.exit(1)
            apps = [app for app in glob.glob(pattern)
                    if os.path.basename(app) != pieces[-4]]
            if len(apps) != 1:
                log.error("%s viewer .app, found %s in %s",
                          ("Ambiguous" if apps else "Missing"), apps, pattern)
                sys.exit(1)
            viewer_binary = os.path.join(apps[0], "Contents", "MacOS", executable_name)
        elif platform.system == "Linux":
            executable_name = "secondlife"
            viewer_binary = os.path.join(os.path.dirname(absfile), executable_name)
        log.debug("viewer binary name: %r" % viewer_binary)

        command = [viewer_binary] + sys.argv[1:]
        #note that we are now using the 2.6 version of subprocess 
        log.warning("Attempting to launch viewer without update check: %r" % command)
        viewer_process = subprocess.Popen(command)
        sys.exit(0)

import collections
from llbase import llsd

#module globals

#imports of other VMP modules
import update_manager

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

@pass_logger
def capture_vmp_args(log, arg_list, cmd_line = None):
    # expected input format: arg_list = ['--set', 'foo', 'bar', '-X', '-Y', 'qux']
    # take a copy of the viewer parameters that are of interest to VMP.
    # the regex for a parameter is --<param> {opt1} {opt2}
    cli_overrides = {}   
    if cmd_line is None:
        cmd_line = get_cmd_line()

    vmp_params = {'--channel':'channel', '--settings':'settings', '--set':'set'}
    # the settings set with --set.  All such settings have only one argument.
    vmp_setters = ('UpdaterServiceSetting', 'UpdaterWillingToTest', 'ForceAddressSize')   

    # Here turn the list into a queue, popping off the left as we go. Note that deque() makes a copy by value, not by reference
    # Because of the complexity introduced by the uncertainty of how many options a parameter can take, this is far less complicated code than the more
    # pythonic (x,y) = <some generator> since we will sometimes have (x), sometimes (x,y) and sometimes (x,y,z)
    # also, because the pop is destructive, we prevent ourselves from iterating back over list elements that iterator methods would peek ahead at
    if arg_list is not None:
        log.info("Parsing passed arguments: %r" % arg_list)
        vmp_queue = collections.deque(arg_list)
        cli_overrides[vmp_params['--set']] = {}
        while vmp_queue:
            param = vmp_queue.popleft()
            #if it is not one of ours, pop through args until we get to the next parameter
            try:
                vmp_param = vmp_params[param]
            except KeyError:
                # param is not one we care about
                continue

            if param == '--set':
                setting_name = vmp_queue.popleft()
                setting_value = vmp_queue.popleft()
                if setting_name in vmp_setters:
                    cli_overrides[vmp_param][setting_name] = setting_value
            else:
                # just skip this one and keep looking for the next known option
                # yes, this will break if someone tries to pass one of our options
                # as the argument to some other option ... they deserve whatever they get
                try:
                    count = cmd_line[vmp_param]['count']
                except KeyError:
                    # cmd_line.xml has no entry for vmp_param, or entry has no
                    # count field
                    log.warning("Command line switch %r not defined in cmd_line.xml", param)
                    # pretend count is 0; don't eat any subsequent args
                    count = 0

                # pop as many additional args as indicated by count
                param_args = [vmp_queue.popleft() for argh in range(count)]
                if count == 1:
                    # in the special case of one arg, store scalar instead of list
                    param_args = param_args[0]

                #the parameter name is the key, the (possibly empty) list of args is the value
                cli_overrides[vmp_param] = param_args

    return cli_overrides

@pass_logger
def main(log, arg_list):
    #main entry point      

    # right away, start interleaving Tkinter with eventlet
    app_window = root()
    eventlet.spawn(TkGreenthread, app_window)

    version=BuildData.get('Version')
    address_size=int(BuildData.get('Address Size'))
    log.info("Viewer version %s (%d bit)" % (version, address_size))

    #find the viewer to be lauched
    viewer_binary = Application.executable()
    log.debug("viewer binary name: %r" % viewer_binary)

    vmp_args = capture_vmp_args(arg_list)
    command = [viewer_binary] + arg_list

    try:
        # update_manager() returns a Runner instance -- or raises UpdateError.
        runner = update_manager.update_manager(command, vmp_args)
    except update_manager.UpdateError as err:
        log.error("Update manager raised %r" % err)
        # use status_message() so the frame will persist until this process
        # terminates
        status_message('%s\nViewer will launch momentarily.' % err)
        runner = PopenRunner(*command)

    # Clear any existing status message: we're about to launch the viewer.
    status_message(None)

    # If runner is actually an ExecRunner, or if the launch attempt fails,
    # this run() call won't return.
    viewer_process = runner.run()

    # at the moment, we just wait here.  Later, the crash monitor will be launched at this point
    rc = viewer_process.wait()
    log.info("Viewer terminated with %s" % rc)
    log.info("Launcher exiting after viewer exit.")

if __name__ == "__main__":
    python_version_check()
    main(sys.argv[1:])
