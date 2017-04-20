import subprocess
import os
import os.path
import sys
import time
import logging
import argparse

#Because of the evolution over time of the specification of VMP, some methods were added "in place", in particular in update manager which should someday be refactored into this
#utility class.  

# ######################

class SL_Logging:
    
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
    def add_verbosity_options(arg_parser, default=logging.WARNING):
        verbosities=arg_parser.add_argument_group('verbosity levels')
        verbosities.add_argument('--quiet',   dest='verbosity', action='store_const', const=logging.ERROR)
        verbosities.add_argument('--verbose', dest='verbosity', action='store_const', const=logging.INFO)
        verbosities.add_argument('--debug',   dest='verbosity', action='store_const', const=logging.DEBUG)
        verbosities.set_defaults(verbosity=default)

    @staticmethod
    def directory():
        """
        Implement the standard Second Life log directory convention,
        with the addition of an environment override for use by tests
        """

        if 'SECONDLIFE_LOGDIR' in os.environ:
            logdir = os.environ['SECONDLIFE_LOGDIR']
        elif sys.platform.startswith('darwin'):
            logdir = os.path.join(os.environ['HOME'],'Library','Application Support','SecondLife','logs')
        elif sys.platform.startswith("win") or sys.platform.startswith("cyg"):
            logdir = os.path.join(os.environ['APPDATA'],'SecondLife','logs')
        elif sys.platform.startswith("linux"):
            logdir = os.path.join(os.environ['HOME'],'.secondlife','logs')
        else:
            #SL doesn't run on VMS or punch cards
            sys.exit("Unsupported platform")

        if not os.path.exists(logdir):
            try:
                os.mkdir(logdir)
            except:
                pass # can't fix it ... ignore it
        return logdir

    @staticmethod
    def rotate(basename, extension):
        """
        Changes basename + extension to basename + '.old'
        Returns basename + extension
        """
        old_name=basename+'.old'
        if os.path.exists(old_name):
            try:
                os.remove(old_name)
            except:
                pass # nothing to be done about this
        new_name=basename+extension
        if os.path.exists(new_name):
            try:
                os.rename(new_name, old_name)
            except:
                pass # nothing to be done about this either
        return new_name

    @staticmethod
    def log(name, args):
        """
        Open the name.log file in the conventional location, with rotation of
        any existing log to name.old.
        Initialize the standard python logging system to log use Second Life
        standard log format.
        Returns the python logging object.
        """
        log_basename=os.path.join(SL_Logging.directory(),name)
        log_name = SL_Logging.rotate(log_basename,'.log')
        log_stream = logging.FileHandler(log_name,'wb')
        log_stream.setFormatter(SL_Logging.Formatter())
        log=logging.getLogger(name)
        log.addHandler(log_stream)
        log.setLevel(args.verbosity)
        return log

#This utility method is lifted from https://github.com/pyinstaller/pyinstaller/wiki/Recipe-subprocess
#and gets us around the issue of pythonw breaking subprocess when default values for I/O handles are used.
#it is slightly modified to always write to the log file rather than provide pipes

#example usage is now 
# subprocess.check_output(['python', '--help'], **subprocess_args(False, log_file_handle)

# Create a set of arguments which make a ``subprocess.Popen`` (and
# variants) call work with or without Pyinstaller, ``--noconsole`` or
# not, on Windows and Linux. Typical use::
#
#   subprocess.call(['program_to_run', 'arg_1'], **subprocess_args())
#
# When calling ``check_output``::
#
#   subprocess.check_output(['program_to_run', 'arg_1'],
#                           **subprocess_args(False))
def subprocess_args(include_stdout=True, handle=None):
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
        ret = {'stdout': handle}
    else:
        ret = {}

    # On Windows, running this from the binary produced by Pyinstaller
    # with the ``--noconsole`` option requires redirecting everything
    # (stdin, stdout, stderr) to avoid an OSError exception
    # "[Error 6] the handle is invalid."
    ret.update({'stdin': subprocess.PIPE,
                'stderr': handle,
                'startupinfo': si,
                'env': env })
    return ret
