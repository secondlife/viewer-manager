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

# Only packages bundled with Python should be imported here.
import platform
import subprocess
import sys

# This must be the FIRST imported module that isn't bundled with Python.
from util import pass_logger, SL_Logging, BuildData, Application
if __name__ == '__main__':
    # Do this right away, before even importing our sibling modules, so that
    # even a crash on import will get logged properly.
    SL_Logging.getLogger('updater')

import eventlet

from SL_Launcher import capture_vmp_args
from runner import PopenRunner
from InstallerUserMessage import status_message, root
import update_manager
from tkeventlet import TkGreenthread

class Error(Exception):
    pass

# ****************************************************************************
#   precheck()
# ****************************************************************************
# This subcommand is typically invoked by the Windows NSIS installer upon
# successful installation. It isn't used on Posix at all -- the point is to
# ensure that the viewer we just installed can run on this system, and if not,
# to download a viewer that can. Only on Windows do we support viewers built
# for different address sizes.
# precheck() is passed the arguments we should pass to the viewer, the first
# of which is the viewer executable itself.
@pass_logger
def precheck(log, viewer, args):
    # cf. SL_Launcher.main()

    # We use a number of other modules, including 'requests'. We want every
    # single module that performs network I/O, or other conventional
    # operations, to perform it using eventlet magic.
    # On Posix, we must pass os=True.
    # On Windows, we must NOT pass os=True.  :-P
    # https://github.com/eventlet/eventlet/issues/483
    eventlet.monkey_patch(os=(platform.system() != 'Windows'),
                          select=True, socket=True, time=True,
                          builtins=True, subprocess=True)

    # right away, start interleaving Tkinter with eventlet in case we want to
    # pop up a status_message()
    eventlet.spawn(TkGreenthread, root())

    log.info("Viewer version {} ({} bit)"
             .format(BuildData.get('Version'), BuildData.get('Address Size')))
    log.debug("viewer binary name: {}".format(viewer))

    # Use of capture_vmp_args() may be overcautious: we know the NSIS
    # installer does not pass any command-line arguments that impact update
    # processing, and the user has no chance to alter them.
    myargs = capture_vmp_args(args)
    command = [viewer] + list(args)

    try:
        # update_manager() returns a Runner instance -- or raises UpdateError.
        runner = update_manager.update_manager(command, myargs)
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

# ****************************************************************************
#   leap()
# ****************************************************************************
# This subcommand is typically invoked by the viewer itself to check for
# updates during a run.
def leap(install_mode, channel, testok, vvmurl, width):
    """
    Pass:
    install_mode: one of the values from the UpdaterServiceSetting combo_box
    channel:      the viewer's actual channel name, as possibly overridden
                  from the viewer command line
    testok:       the viewer's actual UpdaterWillingToTest setting, as
                  possibly overridden from the viewer command line
    vvmurl:       the URL scheme://hostname/update prefix for the Viewer Version
                  Manager to query (from UpdaterServiceURL)
    width:        the ForceAddressSize setting
    """
    params = locals().items()
    params.sort()
    # If we're run as a LEAP child process, anything we write to stderr goes
    # into the viewer log -- so set stderr as our preferred output stream.
    # Because the viewer will timestamp each log line anyway, avoid doubly
    # timestamping each line.
    log = SL_Logging.set_stream(sys.stderr, 'updater', SL_Logging.get_verbosity(),
                                formatter=SL_Logging.TimelessFormatter())
    # Defer importing leap module because its module-level initialization
    # expects LEAP protocol data on sys.stdin
    import leap as _leap

    platform_key = Application.platform_key() # e.g. "mac"

    varwidth = max(len(var) for var, value in params)
    for var, value in params:
        log.info("{} {!r}".format(var.ljust(varwidth), value))

    log.info("Done")

# ****************************************************************************
#   main()
# ****************************************************************************
def main(*raw_args):
    from argparse import ArgumentParser, REMAINDER
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(title='subcommands',
        description='Use %(prog)s <subcommand> --help for help on any subcommand')

    # precheck subcommand
    subprecheck = subparsers.add_parser('precheck',
        help="""Check for update before the first viewer run. If a
        cross-address-size update is required, download and install the
        appropriate viewer. Otherwise, run the specified viewer with the
        specified command-line arguments.""")
    subprecheck.add_argument('viewer',
        help="""Full pathname of the viewer to run""")
    # REMAINDER means anything else on the command line, such as viewer
    # switches -- even viewer switches starting with - or --
    subprecheck.add_argument('args', nargs=REMAINDER,
        help="""command-line arguments to pass to 'viewer'""")
    subprecheck.set_defaults(func=precheck)

    # leap subcommand
    subleap = subparsers.add_parser('leap',
        help="""Check for updates as a LEAP viewer child process""")
    subleap.add_argument('install_mode', type=int,
                         help='UpdaterServiceSetting value')
    subleap.add_argument('channel',
                         help='the running viewer\'s channel name')
    subleap.add_argument('testok', type=bool,
                         help='UpdaterWillingToTest setting')
    subleap.add_argument('vvmurl',
                         help='UpdaterServiceURL setting')
    subleap.add_argument('width', type=int,
                         help='ForceAddressSize setting')
    subleap.set_defaults(func=leap)

    # Parse the command line and invoke appropriate subcommand.
    args = parser.parse_args(raw_args)
    argvars = vars(args)
    # We forced 'func' into each subcommand parser, but no need to pass each
    # function its own identity.
    func = argvars.pop('func')
    # This formulation requires that our subparser add_argument() calls match
    # each function's parameter signature -- which is a Good Thing.
    return func(**argvars)

if __name__ == "__main__":
    try:
        sys.exit(main(*sys.argv[1:]))
    except Error as err:
        sys.exit(str(err))
