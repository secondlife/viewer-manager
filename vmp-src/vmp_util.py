import errno
import json
import logging
import os
import os.path
import platform
import subprocess
import sys
import time

from llbase import llsd

#Because of the evolution over time of the specification of VMP, some methods were added "in place", in particular various getter methods in update manager, which should someday be refactored into this
#utility class.  

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
    def name():
        """Return the conventional application name"""
        channel_base = BuildData.get('Channel Base')
        running_on = platform.system()
        if running_on == 'Darwin':
            executable_name = channel_base
        elif running_on == 'Windows':
            # MAINT-7292: do not infer name from directory; read it from build_data.json as produced by the build
            executable_name = BuildData.get('Executable')
        elif running_on == 'Linux':
            executable_name = ''.join(channel_base.split()) # remove all whitespace
        else:
            #SL doesn't run on VMS or punch cards
            raise Exception("Unsupported platform '%s'" % running_on)
        return executable_name

    @staticmethod
    def app_data_path():
        try:
            # allow tests to override where to look for application data
            return os.environ['APP_DATA_DIR']
        except KeyError:
            pass
        # this is the normal case in the installed app
        if (platform.system() == 'Darwin'):
            app_data_dir = os.path.join(os.path.dirname(__file__), "../Resources")
        else:
            app_data_dir = os.path.dirname(str(sys.executable))
        return os.path.abspath(app_data_dir)

    @staticmethod
    def userpath():
        """Return the conventional location for application specific user files on this platform"""
        application_name = BuildData.get("Channel Base")
        if not application_name:
            # see http://wiki.secondlife.com/wiki/Channel_and_Version_Requirements
            raise KeyError("No 'Channel Base' set in the application metadata; invalid build")
        app_element_nowhite=''.join(application_name.split()) # remove all whitespace

        running_on = platform.system()
        if (running_on == 'Darwin'):
            base_dir = os.path.join(os.path.expanduser('~'),'Library','Application Support',app_element_nowhite)
        elif (running_on == 'Linux'): 
            base_dir = os.path.join(os.path.expanduser('~'))
        elif (running_on == 'Windows'):
            base_dir = os.path.join(os.path.expanduser('~'),'AppData','Roaming',app_element_nowhite)
        else:
            raise ValueError("Unsupported platform '%s'" % running_on)
        return base_dir

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
            sys.exit("Failed to read application build_data: %r %r" % (build_data_file, err))

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
# it is slightly modified to provide for writing to the log file rather than provide pipes

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

#struct used by update_manager and SL_Launcher to update the settings file
#to skip benchmarking for HD graphics cards and passed to write_settings().
skip_settings = {'SkipBenchmark':
                 {'Comment':'Do not benchmark on viewer startup',
                  'Type':'Boolean',
                  'Value':1}}

#same as above for cmd_line.xml
#this tells command line parsers that ForceAddrSize has one argument
skip_cmd = {'ForceAddrSize':
            {'count':1,
             'map-to':'CmdLineForceAddrSize'}}

#utility method to write to the settings file
#settings_object is a parsed/modified python object (dict)
#settings_path is the location of the file to write to
#  usually something like <userpath>/user_settings/settings.xml
#  but left generic here so it can write to other places
#note that format_pretty_xml does the right thing with an empty dict
#caller responsible for catching exceptions and deciding what to do
def write_settings(settings_object=None, settings_path=None):
    #make sure the directory exists to write to
    try:
        os.makedirs(os.path.dirname(settings_path))
    except OSError, ose:
        if ose.errno == errno.EEXIST:
            pass
        else:
            raise
    f = open(settings_path, 'wb')
    with open(settings_path, 'wb') as f:
        f.write(llsd.format_pretty_xml(settings_object))
