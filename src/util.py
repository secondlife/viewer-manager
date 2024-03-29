try:
    import cgitb
except ImportError:
    # sigh
    class cgitb:
        class Hook:
            def __init__(self, file=sys.stderr, format="text"):
                self.file = file
                self.format = format
            def handle(self):
                print("(cgitb unavailable)", file=self.file)
                traceback.print_exc(file=self.file)

import contextlib
import ctypes
import errno
import functools
import itertools
import json
import logging
import os
import os.path
from pathlib import Path
import platform
from io import StringIO
import subprocess
import sys
import tempfile
import time

# Because of the evolution over time of the specification of VMP, some methods
# were added "in place", in particular various getter methods in update
# manager, which should someday be refactored into this utility class.

class Error(Exception):
    pass

# ****************************************************************************
#   ufile(), udir()
# ****************************************************************************
# MAINT-8161: In Python 2 days, in a Mac directory with a Unicode pathname,
# __file__ contained utf8-encoded bytes. Passing that encoded pathname into
# os.path functions would blow up with UnicodeDecodeError. ufile() and udir()
# were to work around that. The workaround is no longer needed.
def ufile(file=__file__):
    """
    Caller may pass own __file__ if desired; or if ufile() is just being
    used to locate the directory path, ufile() suffices since most of our
    callers are in the same directory as this __file__.
    """
    return file

def udir(file=__file__):
    """
    Need only pass own __file__ if you suspect you're in a different directory
    than util.py.
    """
    return os.path.dirname(ufile(file))

# ****************************************************************************
#   getenv()
# ****************************************************************************
# SL-10153: In Python 2, on a Windows system configured with locale English
# (United States) when the username (or any other part of a pathname) is
# non-ASCII, passing such pathnames through the normal process environment
# using normal environment access could produce garbage values because the
# Python 2 interpreter used the A (8-bit) Windows system call entry points
# instead of the W (16-bit) entry points. But with Python 3, we fully expect
# that to work. Continue to support util.getenv() for existing callers.
getenv = os.getenv

# ****************************************************************************
#   pass_logger
# ****************************************************************************
def pass_logger(func):
    """
    This is a convenience interface for SL_Logging.getLogger('function_name').
    Specifically, you can replace this sequence:

    def myfunc(first, second):
        log = SL_Logging.getLogger('myfunc')
        # ... use first, second, log ...

    with this:

    @pass_logger
    def myfunc(log, first, second):
        # ... use first, second, log ...

    It's important to note that myfunc()'s caller still passes only 'first'
    and 'second'. The 'log' parameter is obtained and passed by pass_logger.
    """
    # Define a suitable wrapper function, using functools.wraps() to set its
    # __name__, __module__ and __doc__ from the original func()'s.
    @functools.wraps(func)
    def wrapper(*args, **kwds):
        # Pass the original function's __name__ to getLogger(), as is
        # conventional. Pass all other arguments unchanged. Return the return
        # value unchanged.
        return func(SL_Logging.getLogger(func.__name__), *args, **kwds)

    return wrapper

# ****************************************************************************
#   log_calls
# ****************************************************************************
def log_calls(func):
    """
    This decorator interposes a wrapper that logs entry and exit to the
    decorated 'func', with its parameters and return value (or exception).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwds):
        log = SL_Logging.getLogger(func.__name__)
        log.debug("{}({})".format(func.__name__,
                                  ", ".join(itertools.chain((repr(arg) for arg in args),
                                                            ("%s=%r" % item
                                                             for item in kwds.items())))))
        try:
            result = func(*args, **kwds)
        except Exception as err:
            log.debug("{}() raised {}: {}".format(func.__name__, err.__class__.__name__, err))
            raise
        else:
            log.debug("%s() => %r", func.__name__, result)
            return result

    return wrapper

# ****************************************************************************
#   SL_Logging
# ****************************************************************************
class SL_Logging(object):
    """
    This is a wrapper for the python standard 'logging' class that provides for
    Second Life logging conventions.
    It should be backward-compatible, but relies on the first call to getLogger
    being made through this wrapper to initialize the formatting, put the log file 
    in the correct directory, and rotate any previous log file that has exceeded
    the maximum allowed size.
    """
    logger=None
    logStream=None

    @staticmethod
    def getLogger(basename, extension='.log', verbosity=None, maxsize=10*1024):
        """
        Open the name.log file in the conventional location, with rotation of
        any existing log over the maxsize to name.old
        Initialize the standard python logging system to log use Second Life
        standard log format; the verbosity can be any of:
          'DEBUG', 'INFO', 'WARNING'
        and may be set by environment variable SL_LAUNCH_LOGLEVEL
        the default is 'DEBUG'
        Returns the python logging object.
        """
        if not SL_Logging.logger:
            # before we actually have a log file, buffer any interesting
            # messages
            msgs = StringIO()
            # get an exception handler that writes into that buffer
            handler = cgitb.Hook(file=msgs, format="text")

            try:
                verbosity = SL_Logging.get_verbosity()
            except Exception as err:
                # bad log level shouldn't derail the entire log setup
                verbosity = logging.DEBUG
                print("Setting DEBUG level because: %s" % err, file=msgs)

            try:
                logdir = SL_Logging.directory()
            except Exception as err:
                # directory() depends, among other things, on being able to
                # find and read build_data.json. Even if we can't find the
                # official log directory, put our log file SOMEWHERE.
                logdir = tempfile.gettempdir()
                print("Redirecting log to %r because:" % logdir, file=msgs)
                # get diagnostic info for this exception into msgs
                # while still within the 'except' handler clause
                handler.handle()

            log_basepath=os.path.join(logdir,basename)
            #accomodate verbosity with larger files before rotation
            logsize = maxsize*4 if verbosity == logging.DEBUG else maxsize*2

            try:
                log_name = SL_Logging.rotate(log_basepath, extension=extension, maxsize=logsize)
            except Exception as err:
                print("Growing previous log file because:", file=msgs)
                handler.handle()
                # shrug! Just append to the same log file, despite size!
                log_name = log_basepath + extension

            # If this blows up, we're just hosed.
            SL_Logging.logStream = open(log_name,'a')
            SL_Logging.logger=logging.getLogger(basename)
            SL_Logging.logger.setLevel(verbosity)

            # from this point forward, any unhandled exceptions go into the
            # log file
            # just like cgitb.enable(), except that enable() doesn't support file=
            sys.excepthook = cgitb.Hook(file=SL_Logging.logStream, format="text")

            log = SL_Logging.add_stream(SL_Logging.logStream)
            log.info("================ Running %s" % basename)
            # now log any messages we deferred previously
            for line in msgs.getvalue().splitlines():
                if line:
                    log.warning(line)
            msgs.close()

        else:
            log = SL_Logging.logger.getChild(basename)

        return log

    @staticmethod
    def add_stream(stream, formatter=None):
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter or SL_Logging.Formatter())
        SL_Logging.logger.addHandler(handler)
        return SL_Logging.logger

    @staticmethod
    def get_verbosity():
        verbosity_env = os.getenv('SL_LAUNCH_LOGLEVEL','DEBUG')
        # Except in Python [3.4, 3.4.2), passing a string level name to
        # getLevelName() performs the reverse lookup.
        # https://docs.python.org/3/library/logging.html#logging.getLevelName
        verbosity = logging.getLevelName(verbosity_env)
        if not isinstance(verbosity, int):
            # getLevelName('unknown') returns 'Level unknown' instead of int.
            raise ValueError("Unknown log level %r" % verbosity_env)
        return verbosity

    @staticmethod
    def stream(prefix_msg=""):
        """
        Return the file object that was used to initialize the log stream.
        """
        if prefix_msg:
            SL_Logging.logger.info(prefix_msg)
        return SL_Logging.logStream

    @staticmethod
    def stream_from_process(process, streams="stderr"):
        """
        Specialized wrapper for the stream method that adds a log message
        about the process whose stream may follow in the log.
        Return the file object that was used to initialize the log stream.
        This is provided for use with the subprocess_args method below; by 
        passing this stream to the log_stream parameter of subprocess_args, 
        any stderr output from the subprocess will be directed into the log
        """
        return SL_Logging.stream(prefix_msg="running subcommand %r; any %s follows" %
                                 (process, streams))

    class TimelessFormatter(logging.Formatter):
        """
        Makes python logging follow Second Life log file format, in everything
        but the timestamp
        """
        format_string = "%(levelname)s: %(filename)s(%(lineno)s) : %(funcName)s: %(message)s"

        def __init__(self, format_string=format_string):
            self.sl_format = logging.Formatter(format_string, "%Y-%m-%dT%H:%M:%SZ")
            self.sl_format.converter = time.gmtime

        def format(self, record):
            return self.sl_format.format(record);

        def formatTime(self, record):
            return self.sl_format.format(record);

    class Formatter(TimelessFormatter):
        """
        Add timestamp to each log line
        """
        def __init__(self):
            super(SL_Logging.Formatter, self).__init__("%(asctime)s " +
                                            super(SL_Logging.Formatter, self).format_string)

    @staticmethod
    def directory():
        """
        Implement the standard Second Life log directory convention,
        with the addition of an environment override for use by tests
        """
        # remove all whitespace, upcase
        variable_app_name = (''.join(Application.name().split())).upper()
        logdir=getenv('%s_LOGDIR' % variable_app_name,
                      os.path.join(Application.userpath(), 'logs'))

        with contextlib.suppress(FileExistsError):
            os.makedirs(logdir)

        return logdir

    @staticmethod
    def rotate(basename, extension='.log', maxsize=0):
        """
        Changes basename + extension to basename + '.old'
        Returns basename + extension
        """
        new_name=basename+extension
        if os.path.exists(new_name) and os.path.getsize(new_name) >= maxsize:
            old_name=basename+'.old'
            if os.path.exists(old_name):
                with contextlib.suppress(Exception):
                    os.remove(old_name)
            with contextlib.suppress(Exception):
                os.rename(new_name, old_name)
        return new_name

# ****************************************************************************
#   Application
# ****************************************************************************
class Application(object):

    @staticmethod
    def executable():
        """Return the pathname of the viewer executable"""
        if platform.system() == "Darwin":
            # We are at    Mumble.app/Contents/Resources/updater/util.py
            # Need to find Mumble.app/Contents/MacOS/name
            return os.path.join(Application._darwin_viewer_app_contents_path(),
                                "MacOS", Application.name())
        else:
            # On other platforms, the executable is found in the application
            # install path
            return os.path.join(Application.install_path(), Application.name())

    @staticmethod
    def name():
        """Return the conventional application name"""
        running_on = platform.system()
        if running_on == 'Darwin':
            name = BuildData.get('Channel')
        elif running_on == 'Windows':
            # MAINT-7292: do not infer name from directory; read it from build_data.json as produced by the build
            name = BuildData.get('Executable')
        elif running_on == 'Linux':
            channel_base = BuildData.get('Channel Base')
            name = ''.join(channel_base.split()) # remove all whitespace
        else:
            #SL doesn't run on VMS or punch cards
            raise Error("Unsupported platform '%s'" % running_on)
        return name

    @staticmethod
    def install_path():
        """Return the pathname of the application's install directory"""
        if platform.system() == "Windows":
            # Even on Windows, if we're testing in a normal developer work
            # area, we're using an ordinary Python interpreter with ordinary
            # Python source modules.
            # conflate "sys has no frozen attribute" with "sys.frozen == False"
            if getattr(sys, 'frozen', False):
                # sys.frozen == True: we're in PyInstaller land
                # With PyInstaller, the zipped Python modules are unpacked to
                # a temp directory, so __file__ lives in that temp directory
                # instead of the actual application install directory. To find
                # the install directory we must ask for the main executable --
                # which, with PyInstaller, is the generated exe rather than a
                # separate Python interpreter in a system install.
                return os.path.dirname(sys.executable)

        elif platform.system() == "Darwin":
            # On Darwin, what do we mean by the install directory? Is that the
            # Second Life.app, or the Contents directory, or MacOS, or
            # Resources?
            # We choose to return the Second Life.app directory -- not its
            # Contents, or MacOS, or Resources, but the .app directory itself.
            # sys.executable should be:
            # .../Second Life.app/Contents/Resources/updater/SLVersionChecker
            pieces = Path(sys.executable).resolve().parts
            try:
                if (pieces[-5].endswith(".app")
                    and pieces[-4:-1] == ("Contents", "Resources", "updater")):
                    # include everything up until Mumble.app
                    return str(Path(*pieces[:-4]))
                # developer work area: we're not in the Resources/updater
                # subdirectory at all
            except IndexError:
                # developer work area: there just aren't that many path
                # components in sys.executable
                pass

        # Here we're either not on Windows or Mac, or just running developer
        # tests rather than the packaged application.
        return udir()

    @staticmethod
    def app_data_path():
        # allow tests to override where to look for application data
        APP_DATA_DIR = getenv('APP_DATA_DIR')
        if APP_DATA_DIR:
            return APP_DATA_DIR
        # this is the normal case in the installed app
        if (platform.system() == 'Darwin'):
            # On macOS, find the Resources directory.
            app_data_dir = os.path.join(
                Application._darwin_viewer_app_contents_path(), "Resources")
        else:
            # Everywhere else, just look in the application directory.
            app_data_dir = Application.install_path()
        return os.path.abspath(app_data_dir)

    @staticmethod
    def _darwin_viewer_app_contents_path():
        # On macOS, the updater lives in an 'updater' directory nested under
        # the Second Life.app/Contents/Resources directory.
        # sys.executable should be updater/SLVersionChecker;
        # realpath(updater/../..) should get us Contents.
        return os.path.realpath(os.path.join(os.path.dirname(sys.executable),
                                             os.pardir, os.pardir))

    @staticmethod
    def userpath():
        """Return the conventional location for application specific user files on this platform"""
        application_name = BuildData.get("Channel Base") # e.g. "Second Life"
        if not application_name:
            # see http://wiki.secondlife.com/wiki/Channel_and_Version_Requirements
            raise KeyError("No 'Channel Base' set in the application metadata; invalid build")
        app_element_nowhite=''.join(application_name.split()) # e.g. "SecondLife"

        running_on = platform.system()
        if (running_on == 'Darwin'):
            base_dir = os.path.join(os.path.expanduser('~'),
                                    'Library','Application Support',app_element_nowhite)
        elif (running_on == 'Linux'): 
            base_dir = os.path.join(os.path.expanduser('~'),
                                    '.' + app_element_nowhite.lower())
        elif (running_on == 'Windows'):
            appdata = getenv('APPDATA')
            base_dir = os.path.join(appdata, app_element_nowhite)
        else:
            raise ValueError("Unsupported platform '%s'" % running_on)
        return base_dir

    # Folder ID values for get_folder_path()
    CSIDL_PROGRAMS         = 0x0002
    CSIDL_DESKTOPDIRECTORY = 0x0010
    CSIDL_APPDATA          = 0x001a
    CSIDL_LOCAL_APPDATA    = 0x001c

    @staticmethod
    def get_folder_path(id):
        """
        Windows-only function to return the special folder pathname
        corresponding to the passed ID value.
        """
        # https://docs.python.org/2.7/library/ctypes.html#loading-dynamic-link-libraries
        # "windll libraries call functions using the stdcall calling
        # convention. oledll also uses the stdcall calling convention, and
        # assumes the functions return a Windows HRESULT error code. The error
        # code is used to automatically raise a WindowsError exception when
        # the function call fails."
        dll = ctypes.oledll.shell32
        buf = ctypes.create_unicode_buffer(300)
        # SHGetFolderPath():
        # https://msdn.microsoft.com/en-us/library/windows/desktop/bb762181(v=vs.85).aspx
        # This says new code should use SHGetKnownFolderPath():
        # https://msdn.microsoft.com/en-us/library/windows/desktop/bb762188(v=vs.85).aspx
        # However, the parameters to SHGetKnownFolderPath() are more
        # complicated (therefore harder to fake up with Python ctypes) --
        # you need an entire Python module just to make that one call:
        # https://gist.github.com/mkropat/7550097
        # Therefore just use SHGetFolderPath(), whose parameters are
        # decimal integers documented here:
        # https://msdn.microsoft.com/en-us/library/windows/desktop/bb762494(v=vs.85).aspx
        # Discard HRESULT; trust the oledll assertion documented above.
        dll.SHGetFolderPathW(None, id, None, 0, buf)
        return buf.value

    @staticmethod
    def user_settings_path():
        """Return the conventional location for the user settings file on this platform"""
        return os.path.join(Application.userpath(), "user_settings", "settings.xml")

    PlatformKey = {'Darwin':'mac', 'Linux':'lnx', 'Windows':'win'}
    @staticmethod
    def platform_key():
        #this is the name that is inserted into the VVM URI
        #and carried forward through the rest of the updater to determine
        #platform specific actions as appropriate
        return Application.PlatformKey.get(platform.system())

# ****************************************************************************
#   BuildData
# ****************************************************************************
class BuildData(object):
    """Get information about the application from the metadata in the install"""

    package_data=dict()

    @staticmethod
    def read(build_data_file=None):      
        #get the contents of the build_data.json file.
        if not build_data_file:
            build_data_dir = Application.app_data_path()
            build_data_file = os.path.join(build_data_dir,"build_data.json")

        try:
            with open(build_data_file) as build_data_handle:
                BuildData.package_data=json.load(build_data_handle)
        except Exception as err:
            # without this file, nothing is going to work,
            # so abort immediately with a simple message about the problem
            raise Error("Failed to read %r: %s" % (build_data_file, err))

    @staticmethod
    def get(name ,default=None):
        if not BuildData.package_data:
            BuildData.read()
        return BuildData.package_data.get(name, default)

    @staticmethod
    def override(name, value):
        if not BuildData.package_data:
            BuildData.read()
        BuildData.package_data[name] = value

# ****************************************************************************
#   subprocess_args()
# ****************************************************************************
# This utility method is lifted from https://github.com/pyinstaller/pyinstaller/wiki/Recipe-subprocess
# and gets us around the issue of pythonw breaking subprocess when default values for I/O handles are used.
# it is slightly modified to provide for writing to the log file rather than providing pipes

# example usage is now 
#   subprocess.check_output(['python', '--help'], **subprocess_args(False, log_file_handle)

# Create a set of arguments which make a ``subprocess.Popen`` (and
# variants) call work with or without Pyinstaller, ``--noconsole`` or
# not, on Windows and Linux. Typical use::
#
#   command = ['program_to_run', 'arg_1']
#   message = "message about the included stream for command %r" % command
#   subprocess.call(command, **subprocess_args(log_stream=SL_Logging.stream(prefix_msg=message)))
#
# When calling ``check_output``::
#
#   subprocess.check_output(['program_to_run', 'arg_1'],
#                           **subprocess_args(False))
def subprocess_args(include_stdout=True, log_stream=None):

    try:
        # On Windows, subprocess calls will pop up a command window by default
        # when run from Pyinstaller with the ``--noconsole`` option. Avoid this
        # distraction.
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
    except AttributeError: # normal when not on Windows
        si = None

    # ``subprocess.check_output`` doesn't allow specifying ``stdout``::
    #
    #   Traceback (most recent call last):
    #     File "test_subprocess.py", line 58, in <module>
    #       **subprocess_args(stdout=None))
    #     File "C:\Python27\lib\subprocess.py", line 567, in check_output
    #       raise ValueError('stdout argument not allowed, it will be overridden.')
    #   ValueError: stdout argument not allowed, it will be overridden.
    #
    # So, add it only if it's needed.
    if include_stdout:
        # If we're logging stdout as well as stderr, then tell subprocess to
        # pass literally the same file handle so output interleaves nicely.
        ret = dict(stdout=log_stream, stderr=subprocess.STDOUT)
    else:
        # With Python 3, unless you pass check_output() any of several
        # different optional arguments (e.g. universal_newlines), it returns a
        # bytes object instead of decoding to str.
        ret = dict(stderr=log_stream, encoding='utf-8')

    # On Windows, running this from the binary produced by Pyinstaller
    # with the ``--noconsole`` option requires redirecting everything
    # (stdin, stdout, stderr) to avoid an OSError exception
    # "[Error 6] the handle is invalid."
    ret.update({'stdin': subprocess.PIPE,
                'startupinfo': si })
    return ret

# ****************************************************************************
#   put_marker_file()
# ****************************************************************************
def put_marker_file(dir, ext):
    #mkstemp() returns (file handle, abspath)
    with contextlib.suppress(OSError):
        os.close(tempfile.mkstemp(suffix=ext, dir=dir)[0])

# ****************************************************************************
#   MergedSettings
# ****************************************************************************
class MergedSettings(object):
    """
    This class unifies settings from the settings.xml file (in which each key
    maps to a subdict that has (or should have) a 'Value' key) and a plain
    dict corresponding to command-line --set overrides.
    """
    def __init__(self, settings):
        """pass settings as the contents of a settings.xml file"""
        # We only care about settings entries that have a 'Value' sub-key.
        self.settings = {key: entry['Value'] for key, entry in settings.items()
                         if 'Value' in entry}
        # May or may not be set later; see override_with().
        self.overrides = {}

    def override_with(self, overrides):
        """pass overrides as a plain dict mapping keys to actual values"""
        self.overrides = overrides

    def __bool__(self):
        # not empty if either settings or overrides is non-empty
        return bool(self.overrides) or bool(self.settings)

    def __getitem__(self, key):
        """operator[] method"""
        try:
            # if the key exists in overrides, look no further
            return self.overrides[key]
        except KeyError:
            # okay, look further
            return self.settings[key]

    def get(self, key, default=None):
        try:
            # if the key exists in overrides, look no further
            return self.overrides[key]
        except KeyError:
            # okay, look further
            return self.settings.get(key, default)
