#!/usr/bin/python
"""\
@file   llbase_importer.py
@author Nat Goodspeed
@date   2017-12-05
@brief  This module is an attempt to diagnose mysterious errors importing
        llbase on TeamCity build hosts.

$LicenseInfo:firstyear=2017&license=internal$
Copyright (c) 2017, Linden Research, Inc.
$/LicenseInfo$
"""

import os, sys
import cgitb
from pprint import pprint

_handler = cgitb.Hook(format="text", file=sys.stderr)

# have to define relevant function first so it's available in case import fails
def diagnostics(err, qualifier="", message=None):
    print >>sys.stderr, 72*'='
    print >>sys.stderr, "%s importing llbase%s: %s" % (err.__class__.__name__, qualifier, err)
    if message:
        print >>sys.stderr, message
    print >>sys.stderr, "APP_DATA_DIR = %r" % os.environ['APP_DATA_DIR']
    print >>sys.stderr, "sys.path:"
    pprint(sys.path, sys.stderr)
    _handler.handle()
    print >>sys.stderr, 72*'='
    raise

# first, see if we can import just the package root to discover where it's
# coming from
try:
    import llbase
except Exception as err:
    diagnostics(err)

try:
    # Import all relevant modules so consumer can say (e.g.):
    # from llbase_importer import llsd, llrest
    # But import them on separate lines so traceback will show specifically
    # WHICH import caused the problem.
    from llbase import config
    from llbase import fastest_elementtree
    from llbase import llidl
    from llbase import llrest
    from llbase import llsd
    from llbase import lluuid
    from llbase import tkrestservice
except Exception as err:
    # the point of importing llbase separately is so we can report where we
    # got it from
    diagnostics(err, " modules", message="llbase from %r" % llbase.__file__)

# llbase_importer shouldn't publish a reference to llbase per se
del llbase
