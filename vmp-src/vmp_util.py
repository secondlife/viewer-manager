import subprocess
import os
import os.path
import sys
import time
import logging
import errno

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
            verbosity = self.get_verbosity()
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
    def stream(subcommand, streamname="stderr"):
        """
        Return the file object that was used to initialize the log stream.
        This is provided for use with the subprocess_args method below; by 
        passing this stream to the log_stream parameter of subprocess_args, 
        any stderr output from the subprocess will be directed into the log
        """
        SL_Logging.logger.info("======== running subcommand %r; any %s output follows" % (subcommand, streamname))
        return SL_Logging.logStream

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
        logdir=os.getenv('SECONDLIFE_LOGDIR')
        if not logdir:
            if sys.platform.startswith('darwin'):
                logdir = os.path.join(os.environ['HOME'],'Library','Application Support','SecondLife','logs')
            elif sys.platform.startswith("win") or sys.platform.startswith("cyg"):
                logdir = os.path.join(os.environ['APPDATA'],'SecondLife','logs')
            elif sys.platform.startswith("linux"):
                logdir = os.path.join(os.environ['HOME'],'.secondlife','logs')
            else:
                #SL doesn't run on VMS or punch cards
                sys.exit("Unsupported platform")

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
#   subprocess.call(command, **subprocess_args(log_stream=SL_Logging.stream(command)))
#
# When calling ``check_output``::
#
#   subprocess.check_output(['program_to_run', 'arg_1'],
#                           **subprocess_args(False))
def subprocess_args(include_stdout=True, log_stream=None):
    # The following is true only on Windows.
    if hasattr(subprocess, 'STARTUPINFO'):
        # On Windows, subprocess calls will pop up a command window by default
        # when run from Pyinstaller with the ``--noconsole`` option. Avoid this
        # distraction.
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        # Windows doesn't search the path by default. Pass it an environment so
        # it will.
        env = os.environ
    else:
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
