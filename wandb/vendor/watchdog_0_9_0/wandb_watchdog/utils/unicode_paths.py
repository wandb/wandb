#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 Will Bond <will@wbond.net>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import sys

from wandb_watchdog.utils import platform

try:
    # Python 2
    str_cls = unicode
    bytes_cls = str
except NameError:
    # Python 3
    str_cls = str
    bytes_cls = bytes


# This is used by Linux when the locale seems to be improperly set. UTF-8 tends
# to be the encoding used by all distros, so this is a good fallback.
fs_fallback_encoding = 'utf-8'
fs_encoding = sys.getfilesystemencoding() or fs_fallback_encoding


def encode(path):
    if isinstance(path, str_cls):
        try:
            path = path.encode(fs_encoding, 'strict')
        except UnicodeEncodeError:
            if not platform.is_linux():
                raise
            path = path.encode(fs_fallback_encoding, 'strict')
    return path


def decode(path):
    if isinstance(path, bytes_cls):
        try:
            path = path.decode(fs_encoding, 'strict')
        except UnicodeDecodeError:
            if not platform.is_linux():
                raise
            path = path.decode(fs_fallback_encoding, 'strict')
    return path
