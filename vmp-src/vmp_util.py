import cgitb
import errno
import glob
import json
import logging
import os
import os.path
import platform
from StringIO import StringIO
import subprocess
import sys
import tempfile
import time

from llbase import llsd

#Because of the evolution over time of the specification of VMP, some methods were added "in place", in particular various getter methods in update manager, which should someday be refactored into this
#utility class.  

class Error(Exception):
    pass

# ****************************************************************************
#   ufile(), udir()
# ****************************************************************************
# MAINT-8161: When the viewer is installed into a Mac directory with a Unicode
# pathname, __file__ is utf8-encoded. If we pass that encoded pathname into
# os.path functions, we're likely to blow up with an exception of the form:
# UnicodeDecodeError: 'ascii' codec can't decode byte xx: ordinal not in range(128)
# The fix is simply to ensure that every time we go to reference __file__, we
# apply decode('utf8') first. This function does that for us.
if platform.system() != 'Darwin':
    def ufile(file=__file__):
        return file
else:
    def ufile(file=__file__):
        """
        Caller may pass own __file__ if desired; or if ufile() is just being
        used to locate the directory path, ufile() suffices since most of our
        callers are in the same directory as this __file__.
        """
        return file.decode('utf8')

def udir(file=__file__):
    """
    Need only pass own __file__ if you suspect you're in a different directory
    than vmp_util.py.
    """
    return os.path.dirname(ufile(file))

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
        the default is 'INFO'
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
                print >>msgs, "Setting DEBUG level because: %s" % err

            try:
                logdir = SL_Logging.directory()
            except Exception as err:
                # directory() depends, among other things, on being able to
                # find and read build_data.json. Even if we can't find the
                # official log directory, put our log file SOMEWHERE.
                logdir = tempfile.gettempdir()
                print >>msgs, "Redirecting log to %r because:" % logdir
                # get diagnostic info for this exception into msgs
                # while still within the 'except' handler clause
                handler.handle()

            log_basepath=os.path.join(logdir,basename)
            #accomodate verbosity with larger files before rotation
            logsize = maxsize*4 if verbosity == logging.DEBUG else maxsize*2

            try:
                log_name = SL_Logging.rotate(log_basepath, extension=extension, maxsize=logsize)
            except Exception as err:
                print >>msgs, "Growing previous log file because:"
                handler.handle()
                # shrug! Just append to the same log file, despite size!
                log_name = log_basepath + extension

            # If this blows up, we're just hosed.
            SL_Logging.logStream = open(log_name,'a')

            # from this point forward, any unhandled exceptions go into the
            # log file
            # just like cgitb.enable(), except that enable() doesn't support file=
            sys.excepthook = cgitb.Hook(file=SL_Logging.logStream, format="text")

            log_handler = logging.StreamHandler(SL_Logging.logStream)
            log_handler.setFormatter(SL_Logging.Formatter())

            SL_Logging.logger=logging.getLogger(basename)

            SL_Logging.logger.addHandler(log_handler)

            SL_Logging.logger.setLevel(verbosity)
            SL_Logging.logger.info("================ Running %s" % basename)
            log = SL_Logging.logger
            # now log any messages we deferred previously
            for line in msgs.getvalue().splitlines():
                if line:
                    log.warning(line)
            msgs.close()

        else:
            log = SL_Logging.logger.getChild(basename)

        return log
        
    @staticmethod
    def get_verbosity():
        verbosity_env = os.getenv('SL_LAUNCH_LOGLEVEL','INFO')
        # we COULD just use getattr(logging, verbosity_env) ...
        try:
            verbosity = dict(
                INFO=logging.INFO,
                DEBUG=logging.DEBUG,
                WARNING=logging.WARNING,
                )[verbosity_env]
        except KeyError:
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
        return SL_Logging.stream(prefix_msg="======== running subcommand %r; any %s follows" % (process, streams))

    class Formatter(logging.Formatter):
        """
        Makes python logging follow Second Life log file format
        """
        def __init__(self):
            self.sl_format = logging.Formatter("%(asctime)s %(levelname)s: %(filename)s(%(lineno)s) : %(funcName)s: %(message)s",
                                               "%Y-%m-%dT%H:%M:%SZ"
                                               )
            self.sl_format.converter = time.gmtime

        def format(self, record):
            return self.sl_format.format(record);

        def formatTime(self, record):
            return self.sl_format.format(record);

    @staticmethod
    def directory():
        """
        Implement the standard Second Life log directory convention,
        with the addition of an environment override for use by tests
        """
        variable_app_name = (''.join(Application.name().split())).upper() # remove all whitespace, upcase
        logdir=os.getenv('%s_LOGDIR' % variable_app_name, os.path.join(Application.userpath(), 'logs'))

        try:
            os.makedirs(logdir)
        except OSError as err:
            if err.errno == errno.EEXIST and os.path.isdir(logdir):
                pass
            else:
                raise

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
                try:
                    os.remove(old_name)
                except:
                    pass # nothing to be done about this
            try:
                os.rename(new_name, old_name)
            except:
                pass # nothing to be done about this either
        return new_name

# ****************************************************************************
#   Application
# ****************************************************************************
class Application(object):

    @staticmethod
    def executable():
        """Return the pathname of the viewer executable"""
        if platform.system() == "Darwin":
            # the viewer executable is found inside the bundled
            # Viewer.app/Contents/MacOS
            return os.path.join(Application._darwin_viewer_app_contents_path(),
                                "MacOS", Application.name())
        else:
            # On other platforms, the executable is found in the application
            # install path
            return os.path.join(Application.install_path(), Application.name())

    @staticmethod
    def name():
        """Return the conventional application name"""
        channel_base = BuildData.get('Channel Base')
        running_on = platform.system()
        if running_on == 'Darwin':
            name = channel_base
        elif running_on == 'Windows':
            # MAINT-7292: do not infer name from directory; read it from build_data.json as produced by the build
            name = BuildData.get('Executable')
        elif running_on == 'Linux':
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
                # Unfortunately (MAINT-8078) with Python 2, if the install
                # directory contains non-ASCII characters, neither
                # sys.executable nor sys.argv[0] is usable: Python 2 uses the
                # ASCII variants of the Windows APIs, so any non-ASCII
                # characters in the pathname are translated to plain ASCII
                # question marks. We must ask Windows ourselves.
                return os.path.dirname(Application.get_executable_name())

        elif platform.system() == "Darwin":
            # On Darwin, what do we mean by the install directory? Is that the
            # embedded viewer app or the outer Second Life.app? Is it the
            # Contents directory, or MacOS, or Resources?
            # We choose to return Second Life.app/Contents/MacOS: the
            # directory in which these scripts are found. That's because, when
            # we're running (or testing) in a developer work area rather than
            # an installed app bundle, we still want it to be correct just to
            # return the containing directory.
            pass

        # Here we're either not on Windows or Mac, or just running developer
        # tests rather than the packaged application.
        return udir()

    @staticmethod
    def app_data_path():
        try:
            # allow tests to override where to look for application data
            return os.environ['APP_DATA_DIR']
        except KeyError:
            pass
        # this is the normal case in the installed app
        if (platform.system() == 'Darwin'):
            # On macOS, find the bundled Viewer.app and point to its Resources
            # directory.
            app_data_dir = os.path.join(
                Application._darwin_viewer_app_contents_path(), "Resources")
        else:
            # Everywhere else, just look in the application directory.
            app_data_dir = Application.install_path()
        return os.path.abspath(app_data_dir)

    @staticmethod
    def _darwin_viewer_app_contents_path():
        # This is a little tricky because on macOS, we need to find the viewer
        # app bundle nested under the top-level Second Life.app/Contents/
        # Resources directory. Because the name of the nested app bundle would
        # determine the flyover text for its Dock icon, we want Product to be
        # able to change that name -- but we don't want to have to come back
        # here to tweak this logic whenever they do! Most likely we'll forget,
        # and Bad Things will happen. So instead, rely on our knowledge that
        # it's the only .app bundle under Resources.
        Contents = glob.glob(os.path.join(udir(), os.pardir, "Resources",
                                          "*.app", "Contents"))
        # there had better be exactly one!
        if len(Contents) != 1:
            raise Error("%s viewer .app under %r: found %s" %
                        (("Ambiguous" if Contents else "Missing"),
                         parent, Contents))
        # Extract the only matching pathname; eliminate os.pardir from path.
        return os.path.realpath(Contents[0])

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
            base_dir = os.path.join(os.path.expanduser('~'),'Library','Application Support',app_element_nowhite)
        elif (running_on == 'Linux'): 
            base_dir = os.path.join(os.path.expanduser('~'), app_element_nowhite)
        elif (running_on == 'Windows'):
            appdata = Application.get_folder_path(Application.CSIDL_APPDATA)
            base_dir = os.path.join(appdata, app_element_nowhite)
        else:
            raise ValueError("Unsupported platform '%s'" % running_on)
        return base_dir

    # Folder ID values for get_folder_path()
    CSIDL_APPDATA       = 26
    CSIDL_LOCAL_APPDATA = 28

    @staticmethod
    def get_folder_path(id):
        """
        Windows-only function to return the special folder pathname
        corresponding to the passed ID value.
        """
        import ctypes
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
    def get_executable_name():
        """
        Windows-only function to return the name by which the current process
        was launched. We *should* be able to get this from sys.executable
        and/or sys.argv[0], but Python 2.7 uses ASCII-only versions of the
        applicable Windows APIs, so when the executable pathname contains
        non-ASCII characters, they get translated to question marks. The
        resulting pathname is useless because it doesn't map to anything on
        the actual filesystem.
        """
        # At first we tried to use CommandLineToArgvW():
        # https://msdn.microsoft.com/en-us/library/windows/desktop/bb776391(v=vs.85).aspx
        # This says of CommandLineToArgvW()'s first parameter:
        # "Pointer to a null-terminated Unicode string that contains the full
        # command line. If this parameter is an empty string the function
        # returns the path to the current executable file."
        # GOTCHA (MAINT-8135): If you call CommandLineToArgvW() with an empty
        # string, and the path to the current executable file contains spaces
        # (e.g. "c:\Program Files\Something\Something"), then you get back a
        # list containing [u'C:\\Program', u'Files\\Something\\Something']:
        # the well-known Windows idiocy concerning pathnames with spaces.
        # (Empirically, rejoining those entries with a single space doesn't
        # work because the scan treats multiple spaces as a single space.)
        # (Rejoining them with '*' and passing the result through glob.glob()
        # is TOO inclusive: you also get names without spaces at all, and with
        # other characters instead of spaces.)
        # GOTCHA (MAINT-8150): If you actually call GetCommandLineW() and pass
        # *that* string to CommandLineToArgvW(), then the complete command,
        # spaces and all, is returned in the first entry. However, if the user
        # typed the command at a Command Prompt, you do NOT get the full
        # pathname of the executable -- only what the user typed.
        # Mere eyerolling is inadequate for the occasion.
        # GetModuleFileNameW() *seems* to work better:
        # https://msdn.microsoft.com/en-us/library/windows/desktop/ms683197(v=vs.85).aspx
        # although: 'The string returned will use the same format that was
        # specified when the module was loaded. Therefore, the path can be a
        # long or short file name, and can use the prefix "\\?\".'
        # The following is adapted from:
        # http://nullege.com/codes/search/ctypes.windll.kernel32.GetModuleFileNameW
        import ctypes
        name = ctypes.create_unicode_buffer(1024)
        # "If this [hModule] parameter is NULL [i.e. None], GetModuleFileName
        # retrieves the path of the executable file of the current process."
        rc = ctypes.windll.kernel32.GetModuleFileNameW(None, name, len(name))
        # "If the function fails, the return value is 0 (zero). To get
        # extended error information, call GetLastError."
        if not rc:
            # https://docs.python.org/2/library/ctypes.html#return-types
            # "WinError is a function which will call Windows FormatMessage()
            # api to get the string representation of an error code, and
            # returns an exception. WinError takes an optional error code
            # parameter, if no one is used, it calls GetLastError() to
            # retrieve it."
            raise ctypes.WinError()
        # must've worked
        return name.value

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
        #for linux and windows this file is in the same directory as the script
        #for mac, the script is in ../Contents/MacOS/ and the file is in ../Contents/Resources/
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
        # Windows doesn't search the path by default. Pass it an environment so
        # it will.
        env = os.environ
    except AttributeError: # normal when not on Windows
        si = None
        env = None

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
        ret = dict(stderr=log_stream)

    # On Windows, running this from the binary produced by Pyinstaller
    # with the ``--noconsole`` option requires redirecting everything
    # (stdin, stdout, stderr) to avoid an OSError exception
    # "[Error 6] the handle is invalid."
    ret.update({'stdin': subprocess.PIPE,
                'startupinfo': si,
                'env': env })
    return ret

# ****************************************************************************
#   put_marker_file()
# ****************************************************************************
def put_marker_file(dir, ext):
    #mkstemp() returns (file handle, abspath)
    try:
        os.close(tempfile.mkstemp(suffix=ext, dir=dir)[0])
    except OSError:
        pass

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

    def __nonzero__(self):
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
