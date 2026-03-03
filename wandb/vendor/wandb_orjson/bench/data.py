# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2019-2026), Aarni Koskela (2021)

import gc
from json import dumps as _json_dumps
from json import loads as json_loads

from orjson import dumps as orjson_dumps
from orjson import loads as orjson_loads

from .util import read_fixture


def json_dumps(obj):
    return _json_dumps(obj).encode("utf-8")


LIBRARIES = {
    "orjson": (orjson_dumps, orjson_loads),
    "json": (json_dumps, json_loads),
}


FIXTURE_NAMES = (
    "canada.json",
    "citm_catalog.json",
    "github.json",
    "twitter.json",
)

FIXTURE_AS_BYTES = {name: read_fixture(f"{name}.xz") for name in FIXTURE_NAMES}

FIXTURE_AS_OBJECTS = {
    name: orjson_loads(FIXTURE_AS_BYTES[name]) for name in FIXTURE_NAMES
}


if hasattr(gc, "freeze"):
    gc.freeze()
if hasattr(gc, "collect"):
    gc.collect()
if hasattr(gc, "disable"):
    gc.disable()
