#!/usr/bin/env python3
"""\
@file   nose_tools.py
@author Nat Goodspeed
@date   2022-01-28
@brief  Provide assert_mumble() functions analogous to nose.tools. pytest
        doesn't need them and doesn't provide them. Rather than recasting all
        existing calls to use plain assert with proper operators, provide
        equivalent functions.

$LicenseInfo:firstyear=2022&license=viewerlgpl$
Copyright (c) 2022, Linden Research, Inc.
$/LicenseInfo$
"""

def assert_equal(left, right):
    assert left == right

assert_equals = assert_equal

def assert_is_not_none(expr):
    assert expr is not None

def assert_true(expr):
    assert expr

def assert_false(expr):
    assert not expr
