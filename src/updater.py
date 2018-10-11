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
import os
import platform
import subprocess
import sys
import threading

# This must be the FIRST imported module that isn't bundled with Python.
from util import pass_logger, SL_Logging, BuildData, Application
if __name__ == '__main__':
    # Do this right away, before even importing our sibling modules, so that
    # even a crash on import will get logged properly.
    SL_Logging.getLogger('updater')

import eventlet

from SL_Launcher import capture_vmp_args
from runner import PopenRunner
from InstallerUserMessage import status_message
import update_manager
from leapcomm import ViewerClient, RedirectUnclaimedReqid, ViewerShutdown

# These definitions depend on the viewer's llstartup.h: if EStartupState
# changes, so must they. Much as we would prefer to rely on string names
# alone, we must divide the viewer session into "before clicking Login" vs.
# "after clicking Login", which requires an inequality comparison on the enum
# value.
STATE_LOGIN_WAIT = 3
STATE_WORLD_INIT = 8

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
def leap(install_key, channel, testok, vvmurl, width):
    """
    Pass:
    install_key: one of the numeric values from the UpdaterServiceSetting combo_box
    channel:     the viewer's actual channel name, as possibly overridden
                 from the viewer command line
    testok:      the viewer's actual UpdaterWillingToTest setting, as
                 possibly overridden from the viewer command line
    vvmurl:      the URL scheme://hostname/update prefix for the Viewer Version
                 Manager to query (from UpdaterServiceURL)
    width:       the ForceAddressSize setting
    """
    params = locals().items()
    params.sort()
    # If we're run as a LEAP child process, anything we write to stderr goes
    # into the viewer log -- so add stderr as another logging stream. (Note:
    # we continue writing to our log file anyway for when the updater process
    # must manage a viewer update; in that case the updater must survive the
    # viewer process.)
    # Because the viewer will timestamp each log line anyway, avoid doubly
    # timestamping each line.
    log = SL_Logging.add_stream(sys.stderr,
                                formatter=SL_Logging.TimelessFormatter())
    # This is where we engage LEAP protocol communications, processing the
    # viewer's initialization data.
    viewer = ViewerClient()

    platform_key = Application.platform_key() # e.g. "mac"

    varwidth = max(len(var) for var, value in params)
    for var, value in params:
        log.info("{} {!r}".format(var.ljust(varwidth), value))

    install_mode = update_manager.decode_install_mode(install_key)

    vvm_override = os.getenv("SL_UPDATE_SERVICE")
    if vvm_override and vvm_override != vvmurl:
        vvmurl = vvm_override
        var = "vvmurl"
        value = vvmurl
        log.info("{} {!r}".format(var.ljust(varwidth), value))

    result = update_manager.query_vvm(platform_key=platform_key,
                                      channel=channel,
                                      UpdaterWillingToTest=testok,
                                      UpdaterServiceURL=vvmurl)
    if not result:
        log.info("No update.")
        update_manager.cleanup_previous_download(platform_key)
        return

    result = update_manager.choose_update(platform_key, width, result)
    if not result:
        update_manager.cleanup_previous_download(platform_key)
        return

    log.debug("Chosen result: %s", result)

    if not update_manager.check_install_privs():
        return

    #get download directory, if there are perm issues or similar problems, give up
    try:
        download_dir = update_manager.make_download_dir(result['version'])
    except Exception as e:
        log.error("Error trying to make download dir: %s: %s", e.__class__.__name__, e)
        return

    # determine if we've tried this download before
    downloaded = update_manager.check_for_completed_download(download_dir, result['size'])

    if result['required']:
        log.info("Required update to %s version %s", result['platform'], result['version'])
        if catch_viewer_before_login(viewer, result['version'], "PauseForUpdate"):
            viewer.shutdown()
            # TODO: Is this correct?? Shouldn't we check for partial download?
            if downloaded is None:
                # We haven't yet downloaded the required update -- do so right
                # now, in the foreground, with a progress bar.
                update_manager.download(url=result['url'],
                                        version=result['version'],
                                        download_dir=download_dir,
                                        hash=result['hash'],
                                        size=result['size'],
                                        background=False)
            # Presumably we've just downloaded the new installer.
            # TODO: Wouldn't it make sense for check_for_completed_download()
            # and download() to return the full pathname of the downloaded
            # installer, and for install() to accept that?
            runner = update_manager.install(command=[],
                                            platform_key=platform_key,
                                            download_dir=download_dir)
            runner.run()

        else:
            # We did NOT catch the viewer before login.
            if downloaded is None:
                # At least download it before the next viewer run.
                background_download("required", download_dir, result)

        # Either way, done handling required update.
        return

    # Not a required install, therefore optional. Is the user willing to
    # accept optional updates?
    if 'Install_manual' == install_mode:
        log.info("not installing optional update per UpdaterServiceSetting")
        return

    # Yes the user is willing to accept optional updates. Have we already
    # downloaded this one?
    if downloaded is None:
        # no, download it
        background_download("optional", download_dir, result)
        # and that's all we can do for now, we'll check for completion next run
        return

    if downloaded == 'skip':
        log.info("Skipping this update per previous choice. "
                 "Delete the .skip file in %s to change this.", download_dir)
        return

    if downloaded in ('done', 'next'):
        # found a completed previous download of this optional update
        log.info("Found previously downloaded update in: %s", download_dir)
        # It matters whether the user has clicked Login yet. If we've already
        # logged in, just wait until next time.
        # TODO: That means that a user who always clicks Login really quickly
        # could go for several sessions before being prompted to install an
        # already-downloaded optional update.
        startup_state = viewer.get_startup_state()
        if startup_state.enum > STATE_LOGIN_WAIT:
            log.info("User already clicked Login ({}), deferring"
                     .format(startup_state))
            return

        # If we're still sitting at the login screen, produce a popup and
        # then, once the user closes it, shut down the running viewer and
        # install the new viewer.
        if 'Install_automatically' == install_mode:
            response = viewer.request(
                pump="LLNotifications",
                data=dict(op="requestAdd", name="OptionalUpdateReady",
                          substitutions=dict(VERSION=result['version']),
                          payload={}))
            return

        # 'Install_ask'
        # ask the user what to do with the optional update
        log.info("asking the user what to do with the update")
        response = viewer.request(
            pump="LLNotifications",
            data=dict(op="requestAdd", name="PromptOptionalUpdate",
                      substitutions=dict(VERSION=result['version']),
                      payload={}))
        # The response sent by LLNotifications (packaged as ['response']) is a
        # dict with keys for every button name in the form, one of whose
        # values is True. Trust that only one will be true.
        update_action = next(key for key, value in response['response'].items()
                             if value)
        log.debug("Picked %s from %s", update_action, response['response'])

        if update_action == "Yes":
            log.info("User chose 'Install'")
            viewer.shutdown()
            runner = update_manager.install(command=[],
                                            platform_key=platform_key,
                                            download_dir=download_dir)
            runner.run()
            return

        if update_action == "No":
            log.info("User chose 'Skip'")
            put_marker_file(download_dir, ".skip")
            return

        # Not Now
        log.info("User chose 'Not Now'")
        put_marker_file(download_dir, ".next")
        return

    # should never get here
    log.error("Found nonempty download dir but no marker file. Check returned: %r",
              downloaded)
    return

# ****************************************************************************
#   catch_viewer_before_login()
# ****************************************************************************
@pass_logger
def catch_viewer_before_login(log, viewer, version, notification):
    startup_state = viewer.get_startup_state()
    log.info("Viewer in {}".format(startup_state))
    # In what state is the viewer? It matters whether the user has clicked
    # Login yet.
    if startup_state.enum <= STATE_LOGIN_WAIT:
        # User hasn't yet clicked Login. Pop up a modal viewer
        # notification, pre-empting his/her ability to do that.
        log.info("popping up %s", notification)
        # No timeout; we're waiting for a human being. Patience.
        response = viewer.request(
            pump="LLNotifications",
            data=dict(op="requestAdd", name=notification,
                      substitutions=dict(VERSION=version),
                      payload={}))
        # Presumably it doesn't much matter what's in 'response' ...
        log.info("User acknowledged")
        return True

    # User was too quick on the draw: s/he already clicked Login. Try
    # to intercept at the point of login failure.
    # We can't treat this as a strict request/response handshake; it's
    # too timing-dependent. Login might succeed, in which case we
    # won't get an ack at all -- we'll only find out when the
    # startup_state changes to STATE_WORLD_INIT or beyond.
    reqid = viewer.next_reqid()
    # Temporarily hook on a funky WaitFor instance to capture our ack,
    # if any. Since what we see next might be either our ack or a
    # StartupState change, redirect the possible ack to the
    # WaitForStartup queue. Use a priority that ensures this redirect
    # will see the ack first.
    try:
        with RedirectUnclaimedReqid(viewer.startupWait, viewer, 10, reqid):
            # Now post to the rendezvous point.
            log.info("Posting to LoginSync")
            viewer.send(pump="LoginSync", data=dict(reqid=reqid))
            # Monitor startupWait's queue. Though it seems imprudent to wait
            # without a timeout, the viewer may actually end up prompting
            # the user with PauseForUpdate -- and there's no telling how
            # long it might take the user to acknowledge.
            for event in viewer.startupWait.iterate():
                if event["data"].get("reqid") == reqid:
                    # Oh good, we caught the viewer before login.
                    log.info("got ack from viewer")
                    return True
                # If the startup_state ever gets to STATE_WORLD_INIT or
                # beyond, login is progressing -- we won't ever get an ack.
                if event["pump"] == "StartupState":
                    data = event["data"]
                    startup_state = viewer.State(enum=data.get("enum", 0), str=data.get("str"))
                    if startup_state.enum >= STATE_WORLD_INIT:
                        log.info("Viewer logging in anyway: ({})".format(startup_state))
                        return False
    except ViewerShutdown:
        # It's possible we missed all the cues... but if the next thing we see
        # is ViewerShutdown, that's not an error; don't splash it all over the
        # log file. Just quietly go away.
        pass

# ****************************************************************************
#   background_download()
# ****************************************************************************
@pass_logger
def background_download(log, which, download_dir, result):
    log.info("Found %s update to version %s. Downloading in background to: %s",
             which, result['version'], download_dir)
    # Create and launch a background thread. Because we do NOT set this
    # thread as daemon, the updater process won't terminate until the
    # thread completes.
    background = threading.Thread(
        name="downloader",
        target=update_manager.download,
        kwargs=dict(url=result['url'],
                    version=result['version'],
                    download_dir=download_dir,
                    hash=result['hash'],
                    size=result['size'],
                    background=True))
    background.start()

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
    subleap.add_argument('install_key',
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
