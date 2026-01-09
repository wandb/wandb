# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2018-2025)

import lzma
import os
import sys
import sysconfig
from pathlib import Path
from typing import Any

IS_FREETHREADING = sysconfig.get_config_var("Py_GIL_DISABLED")

SUPPORTS_MEMORYVIEW = sys.implementation == "cpython"

SUPPORTS_GETREFCOUNT = sys.implementation == "cpython"

numpy = None  # type: ignore
if not IS_FREETHREADING:
    try:
        import numpy  # type: ignore # noqa: F401
    except ImportError:
        pass

pandas = None  # type: ignore
if not IS_FREETHREADING:
    try:
        import pandas  # type: ignore # noqa: F401
    except ImportError:
        pass

import pytest

import orjson

data_dir = os.path.join(os.path.dirname(__file__), "../data")

STR_CACHE: dict[str, str] = {}

OBJ_CACHE: dict[str, Any] = {}


def read_fixture_bytes(filename, subdir=None):
    if subdir is None:
        path = Path(data_dir, filename)
    else:
        path = Path(data_dir, subdir, filename)
    if path.suffix == ".xz":
        contents = lzma.decompress(path.read_bytes())
    else:
        contents = path.read_bytes()
    return contents


def read_fixture_str(filename, subdir=None):
    if filename not in STR_CACHE:
        STR_CACHE[filename] = read_fixture_bytes(filename, subdir).decode("utf-8")
    return STR_CACHE[filename]


def read_fixture_obj(filename):
    if filename not in OBJ_CACHE:
        OBJ_CACHE[filename] = orjson.loads(read_fixture_str(filename))
    return OBJ_CACHE[filename]


needs_data = pytest.mark.skipif(
    not Path(data_dir).exists(),
    reason="Test depends on ./data dir that contains fixtures",
)
