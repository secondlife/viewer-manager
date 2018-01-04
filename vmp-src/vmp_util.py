import errno
import glob
import json
import logging
import os
import os.path
import platform
import subprocess
import sys
import tempfile
import time

from llbase import llsd

#Because of the evolution over time of the specification of VMP, some methods were added "in place", in particular various getter methods in update manager, which should someday be refactored into this
#utility class.  

class Error(Exception):
    pass

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
            log_basepath=os.path.join(SL_Logging.directory(),basename)
            #accomodate verbosity with larger files before rotation
            verbosity = SL_Logging.get_verbosity()
            if verbosity == logging.DEBUG:
                logsize = maxsize*4
            else:
                logsize = maxsize*2
            log_name = SL_Logging.rotate(log_basepath, extension=extension, maxsize=logsize)

            SL_Logging.logStream = open(log_name,'a')

            log_handler = logging.StreamHandler(SL_Logging.logStream)
            log_handler.setFormatter(SL_Logging.Formatter())

            SL_Logging.logger=logging.getLogger(basename)

            SL_Logging.logger.addHandler(log_handler)

            SL_Logging.logger.setLevel(SL_Logging.get_verbosity(verbosity))
            SL_Logging.logger.info("================ Running %s" % basename)
            log = SL_Logging.logger

        else:
            log = SL_Logging.logger.getChild(basename)

        return log
        
    @staticmethod
    def get_verbosity(verbosity=None):
        if not verbosity:
            verbosity_env = os.getenv('SL_LAUNCH_LOGLEVEL','INFO')
            if verbosity_env == 'INFO':
                verbosity=logging.INFO
            elif verbosity_env == 'DEBUG':
                verbosity=logging.DEBUG
            elif verbosity_env == 'WARNING':
                verbosity=logging.WARNING
            else:
                raise ValueError("Unknown log level '%s'" % verbosity_env)
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


class Application(object):

    @staticmethod
    def executable():
        """Return the pathname of the viewer executable"""
        if platform.system() == "Darwin":
            # the viewer executable is found inside the companion bundled
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
            # embedded VMP app, or the embedded viewer app, or the outer
            # Second Life.app? Is it the Contents directory, or MacOS, or
            # Resources?
            # We choose to return the outer Second Life.app directory -- not
            # its Contents, or MacOS, or Resources, but the .app directory
            # itself. __file__ should be:
            # somepath/Second Life.app/Contents/Resources/Launcher.app/Contents/MacOS/vmp_util.py
            pieces = os.abspath(__file__).rsplit(os.sep, 6)
            try:
                if (pieces[-7].endswith(".app")
                    and pieces[-6] == "Contents"
                    and pieces[-5] == "Resources"
                    and pieces[-4].endswith(".app")
                    and pieces[-3] == "Contents"
                    and pieces[-2] == "MacOS"):
                    # because we limited rsplit() to 6 splits, pieces[-7] is
                    # "somepath/Second Life.app"
                    return pieces[-7]
                # developer work area: we're not in the embedded Launcher.app
                # in the outer Second Life.app at all
            except IndexError:
                # developer work area: there just aren't that many path
                # components in __file__
                pass

        # Here we're either not on Windows or Mac, or just running developer
        # tests rather than the packaged application.
        return os.path.dirname(__file__)

    @staticmethod
    def app_data_path():
        try:
            # allow tests to override where to look for application data
            return os.environ['APP_DATA_DIR']
        except KeyError:
            pass
        # this is the normal case in the installed app
        if (platform.system() == 'Darwin'):
            # On macOS, we're running in the bundled Launcher.app. Find its
            # sibling Viewer.app and point to its Resources directory.
            app_data_dir = os.path.join(
                Application._darwin_viewer_app_contents_path(), "Resources")
        else:
            # Everywhere else, just look in the application directory.
            app_data_dir = Application.install_path()
        return os.path.abspath(app_data_dir)

    @staticmethod
    def _darwin_viewer_app_contents_path():
        # This is a little tricky because on macOS, we're running in one of
        # two separate app bundles nested under the top-level
        # Second Life.app/Contents/Resources directory. Because the name of
        # each nested app bundle determines the flyover text for its Dock
        # icon, we want Product to be able to change those names -- but we
        # don't want to have to come back here to tweak this logic whenever
        # they do! Most likely we'll forget, and Bad Things will happen. So
        # instead, rely on our knowledge that we're one of the two .app
        # bundles under a common parent -- and we're trying to find the other.
        # This file lives under $myapp/Contents/MacOS. dirname(__file__) is
        # MacOS; realpath(MacOS/../..) should get us myapp.
        parent, myapp = \
            os.path.split(os.path.realpath(os.path.join(os.path.dirname(__file__),
                                                        os.pardir,
                                                        os.pardir)))
        # find all the app bundles under parent, keeping only basenames
        bundles = set(os.path.basename(f)
                      for f in glob.glob(os.path.join(parent, "*.app")))
        # cancel out our own
        bundles.discard(myapp)
        # there had better be exactly one other one!
        if len(bundles) != 1:
            raise Error("%s viewer .app under %r: found %s" %
                        (("Ambiguous" if bundles else "Missing"),
                         parent, bundles))
        # pop the other and return it
        return os.path.join(parent, bundles.pop(), "Contents")

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
            base_dir = os.path.join(os.path.expanduser('~'))
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
        # derived from
        # https://www.programcreek.com/python/example/55296/ctypes.wintypes.LPWSTR
        # N.B.
        # https://msdn.microsoft.com/en-us/library/windows/desktop/bb776391(v=vs.85).aspx
        # says of CommandLineToArgvW()'s first parameter:
        # "Pointer to a null-terminated Unicode string that contains the full
        # command line. If this parameter is an empty string the function
        # returns the path to the current executable file."
        # HOWEVER -- if you call CommandLineToArgvW() with an empty string,
        # and the path to the current executable file contains spaces (e.g.
        # "c:\Program Files\Something\Something"), then you get back a list
        # containing [u'C:\\Program', u'Files\\Something\\Something']: the
        # well-known Windows idiocy concerning pathnames with spaces. If,
        # however, you actually call GetCommandLineW() and pass *that* string
        # to CommandLineToArgvW(), then the complete command pathname, spaces
        # and all, is returned in the first entry. Mere eyerolling is
        # inadequate for the occasion.
        import ctypes
        from ctypes.wintypes import LPWSTR, LPCWSTR, POINTER, HLOCAL
        GetCommandLineW = ctypes.cdll.kernel32.GetCommandLineW
        GetCommandLineW.argtypes = []
        GetCommandLineW.restype = LPCWSTR
        # Use windll instead of oledll since neither of these returns HRESULT.
        CommandLineToArgvW = ctypes.windll.shell32.CommandLineToArgvW
        CommandLineToArgvW.argtypes = [ LPCWSTR, POINTER(ctypes.c_int)]
        CommandLineToArgvW.restype = POINTER(LPWSTR)
        LocalFree = ctypes.windll.kernel32.LocalFree
        LocalFree.argtypes = [HLOCAL]
        LocalFree.restype = HLOCAL
        # variable into which CommandLineToArgvW() will store length of
        # returned array
        argc = ctypes.c_int()
        argv = CommandLineToArgvW(GetCommandLineW(), ctypes.byref(argc))
        try:
            # argv is a pointer, not an array as such -- len(argv) produces a
            # TypeError; argv[:] produces a MemoryError, presumably when we
            # run past the end of the array.
            # argv[:argc.value] is the whole list of results.
            # As long as argc.value >= 1, argv[0] is the executable name.
            if not argc.value:
                raise Error("CommandLineToArgvW() returned empty list")
            # We're about to free argv. Make sure we copy its [0] entry into a
            # new unicode object.
            return unicode(argv[0])
        finally:
            LocalFree(argv)

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
            raise Error("Failed to read %r: %s", build_data_file, err)

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
        ret = {'stdout': log_stream}
    else:
        ret = {}

    # On Windows, running this from the binary produced by Pyinstaller
    # with the ``--noconsole`` option requires redirecting everything
    # (stdin, stdout, stderr) to avoid an OSError exception
    # "[Error 6] the handle is invalid."
    ret.update({'stdin': subprocess.PIPE,
                'stderr': log_stream,
                'startupinfo': si,
                'env': env })
    return ret


def put_marker_file(dir, ext):
    #mkstemp() returns (file handle, abspath)
    try:
        os.close(tempfile.mkstemp(suffix=ext, dir=dir)[0])
    except OSError:
        pass
