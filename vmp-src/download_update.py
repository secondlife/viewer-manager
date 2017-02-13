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
import argparse
from datetime import datetime
import fnmatch
import InstallerUserMessage as IUM
import os.path
import Queue
import requests
#silences InsecurePlatformWarning
# http://stackoverflow.com/questions/29099404/ssl-insecureplatform-error-when-using-requests-package 
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()
import tempfile
import threading
import update_manager

#module default
CHUNK_SIZE = 1024

def silent_write(log_file_handle, text):
    #if we have a log file, write.  If not, do nothing.
    #this is so we don't have to keep trapping for an exception with a None handle
    #oh and because it is best effort, it is also a holey_write ;)
    if (log_file_handle):
       #prepend text for easy grepping
       timestamp = datetime.utcnow().strftime("%m/%d/%Y %H:%M:%S")
       log_file_handle.write(timestamp + " DOWNLOADER: " + text + "\n")

def download_update(url = None, download_dir = None, size = None, progressbar = False, chunk_size = CHUNK_SIZE):
    #url to download from
    #download_dir to download to
    #total size (for progressbar) of download
    #progressbar: whether to display one (not used for background downloads)
    #chunk_size is in bytes, amount to download at once
    
    parent_dir = update_manager.get_parent_path(update_manager.get_platform_key())
    log_file_handle = update_manager.get_log_file_handle(parent_dir, 'downloader.log')
    silent_write(log_file_handle, "In downloader: download_update args %s, %s, %s, %s, %s" % (url, download_dir, size, progressbar, chunk_size))
    silent_write(log_file_handle, "directory to download to: %s" % download_dir)
    queue = Queue.Queue()
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    #the url split provides the basename of the filename
    filename = os.path.join(download_dir, url.split('/')[-1])
    silent_write(log_file_handle, "filename to download to: %s" % filename)
    req = requests.get(url, stream=True)
    down_thread = ThreadedDownload(req, filename, chunk_size, progressbar, queue, log_file_handle)
    down_thread.start()
    silent_write(log_file_handle, "Started download thread.")
    
    if progressbar:
        frame = IUM.InstallerUserMessage(title = "Second Life Downloader", icon_name="head-sl-logo.gif")
        frame.progress_bar(message = "Download Progress", size = size, pb_queue = queue)
        frame.mainloop()
    else:
        #nothing for the main thread to do
        down_thread.join()

class ThreadedDownload(threading.Thread):
    def __init__(self, req, filename, chunk_size, progressbar, in_queue, log_file_handle):
        #req is a python request object
        #target filename to download to
        #chunk_size is in bytes, amount to download at once
        #progressbar: whether to display one (not used for background downloads)
        #in_queue mediates communication between this thread and the progressbar
        threading.Thread.__init__(self)
        self.req = req
        self.filename = filename
        self.chunk_size = int(chunk_size)
        self.progressbar = progressbar
        self.in_queue = in_queue
        self.log_file_handle = log_file_handle
        
    def run(self):
        silent_write(self.log_file_handle, "Download thread running.")
        with open(self.filename, 'wb') as fd:
            #keep downloading until we run out of chunks, then download the last bit
            for chunk in self.req.iter_content(self.chunk_size):
                fd.write(chunk)
                if self.progressbar:
                    #this will increment the progress bar by len(chunk)/size units
                    self.in_queue.put(len(chunk))  
            #signal value saying to the progress bar that it is done and can destroy itself
            #if len(chunk) is ever -1, we get to file a bug against Python
            self.in_queue.put(-1)
            self.cleanup()
            silent_write(self.log_file_handle, "Download thread finished.")
            
    def cleanup(self):
        #on success remove .next file if any and mark done
        download_dir = os.path.dirname(self.filename)
        for fname in os.listdir(download_dir):
            if fnmatch.fnmatch(fname, "*" + '.next'):
                os.remove(os.path.join(download_dir, fname))
        tempfile.mkstemp(suffix=".done", dir=download_dir)    

def main():
    #main method is for standalone use such as support and QA and for background downloading
    #Otherwise, VMP will import this module and run download_update directly
    parser = argparse.ArgumentParser("Download URI to directory")
    parser.add_argument('--url', dest='url', help='URL of file to be downloaded', required=True)
    parser.add_argument('--dir', dest='download_dir', help='directory to be downloaded to', required=True)
    parser.add_argument('--pb', dest='progressbar', help='whether or not to show a progressbar', action="store_true", default = False)
    parser.add_argument('--size', dest='size', help='size of download for progressbar')
    parser.add_argument('--chunk_size', dest='chunk_size', default=CHUNK_SIZE, help='max portion size of download to be loaded in memory in bytes.')
    args = parser.parse_args()

    download_update(url = args.url, download_dir = args.download_dir, size = args.size, progressbar = args.progressbar, chunk_size = args.chunk_size)


if __name__ == "__main__":
    main()
