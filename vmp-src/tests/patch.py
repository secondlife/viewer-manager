#!/usr/bin/env python
"""\
@file   patch.py
@author Nat Goodspeed
@date   2017-08-30
@brief  Provide patch() utility function for test scripts

$LicenseInfo:firstyear=2017&license=viewerlgpl$
Copyright (c) 2017, Linden Research, Inc.
$/LicenseInfo$
"""

from contextlib import contextmanager

@contextmanager
def patch(object, attr, newvalue):
    """
    Usage:

    with patch(module, 'attribute_name', replacement):
        # ...

    For the duration of the 'with' block, any references to the specified
    module's attribute_name attribute will retrieve the replacement value
    instead of the original value.

    The importance of this function is that when the 'with' block exits, by
    any means, the original value of attribute_name will be restored.
    """
    oldvalue = getattr(object, attr)
    setattr(object, attr, newvalue)
    try:
        yield
    finally:
        setattr(object, attr, oldvalue)

@contextmanager
def patch_dict(dct, key, newvalue):
    """
    Usage:

    with patch_dict(somedict, 'key', replacement):
        # ...

    For the duration of the 'with' block, any references to the specified
    dict's key will retrieve the replacement value instead of the original
    value.

    The importance of this function is that when the 'with' block exits, by
    any means, the original value of that key will be restored.
    """
    try:
        oldvalue = dct[key]
    except KeyError:
        # that key didn't exist before: restoring it means deleting it
        def restore():
            del dct[key]
    else:
        # key did exist before: restoring it means assigning oldvalue
        def restore():
            dct[key] = oldvalue

    # now, either way, set the new value
    dct[key] = newvalue

    try:
        # run the body of the 'with' block
        yield dct
    finally:
        # on the way out, restore previous state of dct[key]
        restore()
