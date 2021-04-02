# -*- coding: utf-8 -*-
"""Utility routines
"""

import math


def sweepwarn(s):
    print("[WARNING]", s)


def sweeplog(s):
    print("[LOG]", s)


def sweeperror(s):
    print("[ERROR]", s)


def sweepdebug(s):
    print("[DEBUG]", s)


def pad(lst, num, val=None, left=False):
    pad = [val] * (num - len(lst))
    lst = pad + lst if left else lst + pad
    return lst


def is_nan_or_nan_string(val):
    if isinstance(val, str):
        return val.lower() in ("nan", "inf")
    elif isinstance(val, float):
        return math.isnan(val) or math.isinf(val)
    return False
