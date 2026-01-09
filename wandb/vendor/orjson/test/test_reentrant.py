# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright Anders Kaseorg (2023)
import orjson


class C:
    c: "C"

    def __del__(self):
        orjson.loads('"' + "a" * 10000 + '"')


def test_reentrant():
    c = C()
    c.c = c
    del c

    orjson.loads("[" + "[]," * 1000 + "[]]")
