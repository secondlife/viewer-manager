#!/usr/bin/env python


"""
@file   test_update_manager_query_vvm.py
@author coyot
@date   2016-06-08

$LicenseInfo:firstyear=2016&license=viewerlgpl$
Second Life Viewer Source Code
Copyright (C) 2016, Linden Research, Inc.

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
from nose.tools import *

import logging
import os
import os.path
import platform
import random
import re
import sys
import threading
import with_setup_args

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from vmp_util import SL_Logging, Application, BuildData

BuildData.read(os.path.join(os.path.dirname(__file__),'build_data.json'))

golden_string = """
<?xml version="1.0" ?><llsd><map><key>platforms</key><map><key>win</key>
<map><key>url</key><string>http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_i686_Setup.exe</string>
<key>hash</key><string>08f65e80c15aa5dd9cacc1465840fd38</string><key>size</key><integer>52191576</integer></map><key>mac</key>
<map><key>url</key><string>http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_i386.dmg</string>
<key>hash</key><string>7f4fa9ff0ea20b0f6b4c907247d866b2</string><key>size</key><integer>78364790</integer></map><key>lnx</key>
<map><key>url</key><string>http://download.cloud.secondlife.com/Viewer_4/Second_Life_4_0_1_310054_i686.tar.bz2</string>
<key>hash</key><string>5c4108145f344b0cbe922182241005ed</string><key>size</key><integer>41938388</integer></map></map>
<key>required</key><boolean>false</boolean><key>version</key><string>4.0.1.310054</string>
<key>channel</key><string>SecondLifeRelease</string><key>more_info</key><string>https://wiki.secondlife.com/wiki/Release_Notes/Second_Life_Release/4.0.1.310054</string></map></llsd>
"""

def test_query_vvm():
    log=SL_Logging.getLogger('test_update_query_vvm', verbosity='DEBUG')
    channel_pattern = re.compile("SecondLife")
    url_pattern = re.compile("Second_Life_4_0_1_310054")
    log.info("Starting Query VVM Test")
    
    #cygwin artifact: the installed llbase is in a cygwin directory but we
    #use system python and it doesn't know from cygpaths, so the import misses
    #and we get the system llbase instead.
    windows = re.compile('win')
    if windows.search(sys.platform.lower()):                     
        local_llbase = os.path.join(os.path.dirname(os.path.abspath(os.getcwd())), 
            'stage', 'packages', 'lib', 'python')
        os.environ['PYTHONPATH'] = local_llbase
        sys.path.insert(0, local_llbase)
    from llbase import llsd
    from llbase import llrest    
    log.error("llrest location in unit test: %r" % llrest.__file__)
    import update_manager    
    
    #for unit testing purposes, just testing a value from results.  
    #for formal QA see:
    #   https://docs.google.com/document/d/1WNjOPdKlq0j_7s7gdNe_3QlyGnQDa3bFNvtyVM6Hx8M/edit
    #   https://wiki.lindenlab.com/wiki/Login_Test#Test_Viewer_Updater
    #for test plans on all cases, as it requires setting up a truly functional fake VVM service
    #pick a random, unused port to serve on
    found_port = False
    httpd = None
    results = None
    
    while not found_port:
        port = random.randint(1025,65535) 
        log.info("trying a port for server: " + str(port))
        try:
            httpd = Server(('', port), TestHTTPRequestHandler)    
        except:
            pass
        finally:
            if httpd is not None:
                found_port = True
                log.info("httpd: %r" % httpd)
                log.info("found a port for server: " + str(port))
            else:
                log.info("httpd is None")
    
    matt = threading.Thread(name='vvm_daemon', args=(httpd,), target=vvm_daemon)
    matt.setDaemon(True)    
    matt.start()

    results = update_manager.query_vvm(platform_key=Application.platform_key(), settings=None, UpdaterServiceURL='http://localhost:'+str(port)+'/update')

    assert results
    assert channel_pattern.search(results['channel']), "Bad results returned %s" % str(results)
    assert url_pattern.search(results['url']), "Bad results returned %s" % str(results)
    
def vvm_daemon(webserver):
    log=SL_Logging.getLogger('vvm_daemon', verbosity='DEBUG')
    log.info("Daemon webserver starting")
    webserver.serve_forever()
    log.info("Daemon webserver exiting")

class TestHTTPRequestHandler(BaseHTTPRequestHandler):
    log=SL_Logging.getLogger('TestHTTPRequestHandler', verbosity='DEBUG')
    def do_GET(self, withdata=True):
        self.log.info("Answering URI request %r "% self.path)
        try:
            response = golden_string
            self.send_response(200)
            self.send_header("Content-type", "application/llsd+xml")
            self.send_header("Content-Length", str(len(response)))
            self.send_header("X-LL-Special", "Mememememe");
            self.end_headers()
            if withdata:
                self.wfile.write(response)            
        except Exception, e:
            print >> sys.stderr, "Exception during GET (ignoring): %s" % str(e)    

#ripped from llcorehttp tests
class Server(HTTPServer):
    # This pernicious flag is on by default in HTTPServer. But proper
    # operation of freeport() absolutely depends on it being off.
    allow_reuse_address = False

    # Override of BaseServer.handle_error().  Not too interested
    # in errors and the default handler emits a scary traceback
    # to stderr which annoys some.  Disable this override to get
    # default behavior which *shouldn't* cause the program to return
    # a failure status.
    def handle_error(self, request, client_address):
        print '-'*40
        print 'Ignoring exception during processing of request from',
        print client_address
        print '-'*40
