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

# Make a distinguished value other than None: caller might want to use
# patch_dict() to temporarily set a particular dict value None.
DELETE = object()

@contextmanager
def patch_dict(dct, key, newvalue):
    """
    Usage:

    with patch_dict(somedict, 'key', replacement):
        # ...

    For the duration of the 'with' block, somedict['key'] will retrieve the
    replacement value instead of the original value.

    Alternatively:

    with patch_dict(somedict, 'key', DELETE):
        # ...

    For the duration of the 'with' block, somedict['key'] will raise KeyError.

    The importance of this function is that when the 'with' block exits, by
    any means, the original value of that key will be restored. If somedict
    had no such key, it will be deleted again.
    """
    try:
        oldvalue = dct[key]
    except KeyError:
        # that key didn't exist before: restoring it means deleting it
        def restore():
            # discard dct[key] if it exists
            dct.pop(key, None)
    else:
        # key did exist before: restoring it means assigning oldvalue
        def restore():
            dct[key] = oldvalue

    # now, either way, set the new value
    if newvalue is DELETE:
        # discard dct[key] if it exists
        dct.pop(key, None)
    else:
        dct[key] = newvalue

    try:
        # run the body of the 'with' block
        yield dct
    finally:
        # on the way out, restore previous state of dct[key]
        restore()
