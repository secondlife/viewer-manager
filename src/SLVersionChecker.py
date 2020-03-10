#!/usr/bin/python
"""\
@file   SLVersionChecker.py
@author Nat Goodspeed
@date   2018-09-12
@brief  Query, download and install viewer updates as required.

$LicenseInfo:firstyear=2018&license=viewerlgpl$
Copyright (c) 2018, Linden Research, Inc.
$/LicenseInfo$
"""

# Only packages bundled with Python should be imported here.
import errno
import os
import platform
import shutil
import sys

# This must be the FIRST imported module that isn't bundled with Python.
from util import pass_logger, SL_Logging, BuildData, Application
if __name__ == '__main__':
    # Do this right away, before even importing our sibling modules, so that
    # even a crash on import will get logged properly.
    SL_Logging.getLogger('SLVersionChecker')

# Temporary workaround for "import eventlet" crash SL-11563,
# normaly eventlet should not reqire any pre-improting
import dns
from eventlet.hubs import epolls
from eventlet.hubs import kqueue
from eventlet.hubs import poll
from eventlet.hubs import selects
import eventlet

import apply_update
from SL_Launcher import capture_vmp_args
from runner import Runner, PopenRunner
from InstallerUserMessage import status_message, AppDestroyed
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

    # SL-10153: If the viewer is installed on a path that includes non-ASCII
    # characters, we fail to launch it because non-ASCII characters are
    # replaced with ASCII '?'. Since the NSIS installer supports Unicode,
    # presumably its Exec verb uses CreateProcessW(), which can presumably
    # pass non-ASCII command-line arguments. However, Python 2 doesn't seem to
    # deal well with non-ASCII command-line parsing. Thing is, we should
    # already be able to determine the name of our target executable.
    executable = Application.executable()
    if executable != viewer:
        log.warning("Overriding '%s' with '%s'", viewer, executable)
        if os.path.basename(executable) != os.path.basename(viewer):
            log.warning("  despite difference in basename")
        viewer = executable

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
    log.debug("viewer binary name: %s", viewer)

    # SL-9980: If this is a Standard Windows user, who had to respond to a UAC
    # prompt to get Admin privilege for the NSIS installer, and we simply
    # launch the viewer -- as far as the viewer can tell, it was launched by
    # the Admin user. It will read (and update) the Admin user's settings. It
    # will record log files in the Admin user's logs directory. It will cache
    # in the Admin user's cache directory ... etc. etc. Use conventional
    # explorer.exe hack to slough off Admin privilege if we have it. Since
    # explorer.exe only accepts one argument, pass it the shortcut, which
    # packages up all other arguments of interest.
    # But since the shortcut's name varies, read it from BuildData.
    # Because the viewer's directory pathname might contain non-ASCII
    # characters, direct PopenRunner to navigate to that directory and then
    # point explorer.exe to the shortcut name.
    # Prepend os.curdir to prevent Windows from launching whichever shortcut
    # by that name is on the current PATH.
    runner = PopenRunner(os.path.join(os.environ['WINDIR'], 'explorer.exe'),
                         os.path.join(os.curdir, BuildData.get('AppName') + '.lnk'),
                         cwd=os.path.dirname(viewer))

    try:
        # update_manager() returns a Runner instance -- or raises UpdateError.
        runner = update_manager.update_manager(runner)
    except update_manager.UpdateError as err:
        log.error("Update manager raised %r" % err)
        # use status_message() so the frame will persist until this process
        # terminates
        try:
            status_message('%s\nViewer will launch momentarily.' % err)
        except AppDestroyed as e:
            log.exception("User attempted to quit")
            sys.exit(1)
        except Exception as e:
            log.exception("Failed to update UI")
            sys.exit(-1)

    # Clear any existing status message: we're about to launch the viewer.
    try:
        status_message(None)
    except AppDestroyed as e:
        log.exception("User attempted to quit")
        sys.exit(1)
    except Exception as e:
        log.exception("Failed to update UI")
        sys.exit(-1)

    # If runner is actually an ExecRunner, or if the launch attempt fails,
    # this run() call won't return.
    viewer_process = runner.run()

# ****************************************************************************
#   leap()
# ****************************************************************************
# This subcommand is typically invoked by the viewer itself to check for
# updates during a run.
def leap(*args, **kwds):
    """
    Intercept control between leap_body() and its caller so we can perform
    some cleanup work on return.
    """
    log = SL_Logging.getLogger('leap')
    try:
        leap_body(*args, **kwds)
    except ViewerShutdown:
        # SL-10683: if we hit ViewerShutdown when we're *not* expecting it,
        # just silently steal away. For instance, when the viewer crashes on
        # startup, we can't even set up our communications protocol.
        # (Well, not quite silently.)
        log.error("Viewer terminated abruptly, shutting down")
        return
    except update_manager.UpdateError as err:
        # Updater likely have been closed by user, but even in case of genuine failure
        # we do not handle such case anywhere below, so just log and return 
        log.exception("Unhandled exception in leap_body")
        return

    # SL-10469: Along about December 2018, there was a BugSplat RC viewer that
    # permitted Windows per-user installs. This was later deemed unworkable
    # (see SL-10396). However, a user who had previously performed a per-user
    # install might be left with confusing and possibly dangling shortcuts.
    # We can't reliably make the current NSIS installer remove them because,
    # if the current user is a Standard Windows user, s/he must seek Admin
    # privilege elevation to run the installer at all -- and once the
    # installer is running as Admin, Windows won't divulge the identity of the
    # original Standard user. We could try to delete any such shortcuts for
    # the Admin user, but that would do nothing for the Standard user.
    # Similarly, our precheck() function is run with Admin still in effect.
    # Not until we get to leap() are we sure to be running with the real
    # Windows login user's identity.
    # This ugliness only pertains to Windows.
    if platform.system() != 'Windows':
        return

    # The shortcuts of interest would be found in (e.g.)
    # c:\Users\<username>\
    #   AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Second Life Viewer\*.*
    #   Desktop\Second Life Viewer.lnk
    # We can get Windows to tell us the Start Menu\Programs folder
    # (CSIDL_PROGRAMS) and Desktop (CSIDL_DESKTOPDIRECTORY) so we'll find them
    # even on oddly-configured systems. The other essential information is our
    # own application name, found in BuildData.get('AppName').
    appname  = BuildData.get('AppName')
    local_progsdir = os.path.join(Application.get_folder_path(Application.CSIDL_PROGRAMS),
                                  appname)
    try:
        shutil.rmtree(local_progsdir)
    except OSError as err:
        # Absence of local_progsdir is the normal case. Don't squawk.
        if err.errno != errno.ENOENT:
            # This is best-effort cleanup: even if it fails, carry on regardless.
            log.warning("Couldn't delete old shortcuts at '%s': %s", local_progsdir, err)
    else:
        # we actually deleted something -- log it for forensic purposes
        log.info("Deleted old shortcuts at '%s'", local_progsdir)

    local_desktop_shortcut = os.path.join(Application.get_folder_path(Application.CSIDL_DESKTOPDIRECTORY),
                                          appname + '.lnk')
    try:
        os.remove(local_desktop_shortcut)
    except OSError as err:
        # absence is the normal case
        if err.errno != errno.ENOENT:
            # still only best-effort
            log.warning("Couldn't delete old shortcut at '%s': %s", local_desktop_shortcut, err)
    else:
        # actually deleted it
        log.info("Deleted old shortcut at '%s'", local_desktop_shortcut)

def leap_body(install_key, channel, testok, width):
    """
    Pass:
    install_key: one of the numeric values from the UpdaterServiceSetting combo_box
    channel:     the viewer's actual channel name, as possibly overridden
                 from the viewer command line
    testok:      the viewer's actual UpdaterWillingToTest setting, as
                 possibly overridden from the viewer command line
    width:       the ForceAddressSize setting
    """
    # This first: the only way to capture params is as a snapshot of locals(),
    # so do that before cluttering locals() with local variable assignments.
    params = locals().items()
    # If we're run as a LEAP child process, anything we write to stderr goes
    # into the viewer log -- so add stderr as another logging stream. (Note:
    # we continue writing to our log file anyway for when the updater process
    # must manage a viewer update; in that case the updater must survive the
    # viewer process.)
    # Because the viewer will timestamp each log line anyway, avoid doubly
    # timestamping each line.
    log = SL_Logging.add_stream(sys.stderr,
                                formatter=SL_Logging.TimelessFormatter())

    varwidth = max(len(var) for var, value in params)
    params.sort()
    for var, value in params:
        log.info("{} {!r}".format(var.ljust(varwidth), value))

    # This is where we engage LEAP protocol communications, processing the
    # viewer's initialization data.
    viewer = ViewerClient()

    platform_key = Application.platform_key() # e.g. "mac"
    install_mode = update_manager.decode_install_mode(install_key)

    result = update_manager.query_vvm(platform_key=platform_key,
                                      channel=channel,
                                      UpdaterWillingToTest=testok)
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
                installer = download(
                    which="required", download_dir=download_dir, result=result, ui=True)
            else:
                installer = apply_update.get_filename(download_dir)
            # Presumably we've just downloaded the new installer.
            install(platform_key=platform_key, installer=installer)

        else:
            # We did NOT catch the viewer before login.
            if downloaded is None:
                # At least download it before the next viewer run. Download it
                # silently (no UI), inline on this same thread -- we're not
                # doing anything else anyway.
                installer = download(which="required", download_dir=download_dir,
                                     result=result, ui=False)

        # Either way, done handling required update.
        return

    # Not a required install, therefore optional. Is the user willing to
    # accept optional updates?
    if 'Install_manual' == install_mode:
        log.info("not installing optional update per UpdaterServiceSetting")
        return

    # Yes the user is willing to accept optional updates. Have we already
    # prompted? Did the user direct us to skip this particular version?
    if downloaded == 'skip':
        log.info("Skipping this update per previous choice. "
                 "Delete the .skip file in %s to change this.", download_dir)
        return

    # Have we already downloaded this one?
    if downloaded is None:
        # no, silently download it inline on this same thread -- we're not
        # doing anything else anyway.
        installer = download(which="optional", download_dir=download_dir,
                             result=result, ui=False)
        # If we're still sitting at the Login screen, may as well proceed.
        process_optional_update(
            viewer=viewer, installer=installer, version=result['version'],
            install_mode=install_mode, platform_key=platform_key)
        return

    if downloaded in ('done', 'next'):
        # found a completed previous download of this optional update
        log.info("Found previously downloaded update in: %s", download_dir)
        installer = apply_update.get_filename(download_dir)
        process_optional_update(
            viewer=viewer, installer=installer, version=result['version'],
            install_mode=install_mode, platform_key=platform_key)
        return

    # should never get here
    log.error("Found nonempty download dir '%s' but no marker file. Check returned: %r",
              download_dir, downloaded)
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
        try:
            response = viewer.request(
                pump="LLNotifications",
                data=dict(op="requestAdd", name=notification,
                          substitutions=dict(VERSION=version),
                          payload={}))
        except ViewerShutdown:
            log.info("User closed the viewer")
            return True
        else:
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
                data = event["data"]
                if data.get("reqid") == reqid:
                    # Oh good, we caught the viewer before login.
                    log.info("got ack from viewer: %s", data)
                    # The viewer indicates whether we should proceed.
                    return data.get("update", False)
                # If the startup_state ever gets to STATE_WORLD_INIT or
                # beyond, login is progressing -- we won't ever get an ack.
                if event["pump"] == "StartupState":
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
#   process_optional_update()
# ****************************************************************************
@pass_logger
def process_optional_update(log, viewer, installer, version, install_mode, platform_key):
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

    # We're still sitting at the login screen. At this point, our response
    # depends on install_mode.
    if 'Install_automatically' == install_mode:
        # produce a popup and then, once the user closes it, shut down the
        # running viewer and install the new viewer.
        try:
            response = viewer.request(
                pump="LLNotifications",
                data=dict(op="requestAdd", name="OptionalUpdateReady",
                          substitutions=dict(VERSION=version), payload={}))
        except ViewerShutdown:
            # User closed the viewer instead of clicking OK -- same thing.
            pass
        else:
            viewer.shutdown()
        install(platform_key=platform_key, installer=installer)
        return

    if 'Install_ask' == install_mode:
        # ask the user what to do with the optional update
        log.info("asking the user what to do with the update")
        try:
            response = viewer.request(
                pump="LLNotifications",
                data=dict(op="requestAdd", name="PromptOptionalUpdate",
                          substitutions=dict(VERSION=version), payload={}))
        except ViewerShutdown:
            # User closed the viewer.
            log.info("User closed viewer without confirming optional update, assuming 'Not Now'")
            update_manager.put_marker_file(os.path.dirname(installer), ".next")
            return

        # The response sent by LLNotifications (packaged as ['response']) is a
        # dict with keys for every button name in the form, one of whose
        # values is True. Trust that exactly one will be true.
        update_action = next(key for key, value in response['response'].items()
                             if value)
        log.debug("Picked %s from %s", update_action, response['response'])

        if update_action == "Yes":
            log.info("User chose 'Install'")
            viewer.shutdown()
            install(platform_key=platform_key, installer=installer)
            return

        if update_action == "No":
            log.info("User chose 'Skip'")
            update_manager.put_marker_file(os.path.dirname(installer), ".skip")
            return

        # Not Now
        log.info("User chose 'Not Now'")
        update_manager.put_marker_file(os.path.dirname(installer), ".next")
        return

    log.warning("Unrecognized install_mode: %r", install_mode)

# ****************************************************************************
#   download()
# ****************************************************************************
@pass_logger
def download(log, which, download_dir, result, ui=True):
    log.info("Found %s update to version %s. Downloading%s to: %s",
             which, result['version'], ("" if ui else " in background"), download_dir)
    return update_manager.download(url=result['url'],
                                   version=result['version'],
                                   download_dir=download_dir,
                                   hash=result['hash'],
                                   size=result['size'],
                                   ui=ui)

# ****************************************************************************
#   install()
# ****************************************************************************
def install(platform_key, installer):
    # The Runner we pass is used only to extract any possible command-line
    # arguments. We're not passing any.
    runner = update_manager.install(runner=Runner(), platform_key=platform_key,
                                    installer=installer)
    runner.run()

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
