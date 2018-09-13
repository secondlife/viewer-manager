#!/usr/bin/env python

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
@file   download_update.py
@author coyot
@date   2016-06-23
"""

"""
Performs a download of an update.  In a separate script from update_manager so that we can
call it with subprocess.
"""
import os
from datetime import datetime
import errno
import glob
import InstallerUserMessage as IUM
import os.path
import requests
import sys
#silences InsecurePlatformWarning
# http://stackoverflow.com/questions/29099404/ssl-insecureplatform-error-when-using-requests-package 
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()
import tempfile
import time
from vmp_util import SL_Logging, Application

#module default
# MAINT-8082: empirically, if this isn't big enough, it can actually slow
# downloads on the Mac
CHUNK_SIZE = 1024*1024

class DummyProgressBar(object):
    def step(self, value):
        pass

    def progress_done(self):
        pass

#Note: No exception handling here! Response to exceptions is the responsibility of the caller
def download_update(url, download_dir, size, progressbar = False, chunk_size = CHUNK_SIZE):
    #url to download from
    #download_dir to download to
    #total size (for progressbar) of download
    #progressbar: whether to display one (not used for background downloads)
    #chunk_size is in bytes, amount to download at once

    log=SL_Logging.getLogger('download_update')
    log.info("Downloading new viewer from %r to %r" % (url, download_dir))
    log.debug(" url %s, download_dir %s, size %s, progressbar %s, chunk_size %s",
              url, download_dir, size, progressbar, chunk_size)
    try:
        os.makedirs(download_dir)
    except OSError as err:
        # fine if it already exists, other errors not fine
        if err.errno != errno.EEXIST:
            raise
    #the url split provides the basename of the filename
    filename = os.path.join(download_dir, url.split('/')[-1])
    log.info("downloading to: %s" % filename)
    req = requests.get(url, stream=True)

    if progressbar:
        progress = IUM.root()
        progress.progress_bar(message = "Download Progress", size = size)
    else:
        progress = DummyProgressBar()

    # ensure that we clean up the progress bar, no matter how we leave
    try:
        start = time.time()
        completed = 0
        log_interval = 60
        log_next = start + log_interval
        with open(filename, 'wb') as fd:
            #keep downloading until we run out of chunks
            for chunk in req.iter_content(chunk_size):
                fd.write(chunk)
                completed += len(chunk)
                #this will increment the progress bar by len(chunk)/size units
                progress.step(len(chunk))

                # Add periodic download log messages. When we start a background
                # download on a separate thread, the main thread might complete --
                # and produce log output to that effect -- yet the process lives
                # on. Occasional log messages help the curious user remember that.
                now = time.time()
                if now >= log_next:
                    log_next = now + log_interval
                    if completed == 0:
                        # still nothing?! no prediction possible
                        eta = "---"
                    else:
                        # once we've downloaded even the first chunk, we can
                        # start to make wild guesses about completion
                        elapsed = now - start
                        # completed/size predicts elapsed/totaltime
                        # totaltime * (completed/size) = elapsed
                        # totaltime = elapsed / (completed / size)
                        # totaltime = elapsed * size / completed
                        totaltime = elapsed * float(size) / completed
                        eta = start + totaltime
                        # use gmtime and the same time format as
                        # SL_Logging.Formatter.sl_format
                        eta = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(eta))
                    log.info("downloaded %s bytes; %s%% complete; ETA %s",
                             completed, int(100*float(completed)/size), eta)
    finally:
        progress.progress_done()

    #on success remove .next file if any
    for fname in glob.glob(os.path.join(download_dir, "*" + '.next')):
        os.remove(fname)
    # and mark done
    # mkstemp() returns (OS file handle, absolute pathname)
    os.close(tempfile.mkstemp(suffix=".done", dir=download_dir)[0])
    log.info("Download finished.")
    # show caller the pathname of the file we downloaded
    return filename

def main():
    import argparse
    parser = argparse.ArgumentParser("Download URI to directory")
    parser.add_argument('--url', dest='url', help='URL of file to be downloaded', required=True)
    parser.add_argument('--dir', dest='download_dir', help='directory to be downloaded to', required=True)
    parser.add_argument('--pb', dest='progressbar', help='whether or not to show a progressbar', action="store_true", default = False)
    parser.add_argument('--size', dest='size', help='size of download for progressbar')
    parser.add_argument('--chunk_size', dest='chunk_size', default=CHUNK_SIZE, help='max portion size of download to be loaded in memory in bytes.')
    args = parser.parse_args()

    download_update(url = args.url,
                    download_dir = args.download_dir,
                    size = args.size,
                    progressbar = args.progressbar,
                    chunk_size = args.chunk_size)

if __name__ == "__main__":
    # Initialize the python logging system to SL Logging format and destination
    SL_Logging.getLogger('SL_Downloader')

    main()
