# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright Aarni Koskela (2021), ijl (2019)

from json import dumps as _json_dumps
from json import loads as json_loads

from orjson import dumps as orjson_dumps
from orjson import loads as orjson_loads


def json_dumps(obj):
    return _json_dumps(obj).encode("utf-8")


libraries = {
    "orjson": (orjson_dumps, orjson_loads),
    "json": (json_dumps, json_loads),
}


fixtures = [
    "canada.json",
    "citm_catalog.json",
    "github.json",
    "twitter.json",
]
