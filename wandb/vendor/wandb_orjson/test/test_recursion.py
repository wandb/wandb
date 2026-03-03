# SPDX-License-Identifier: MPL-2.0
# Copyright ijl (2026)


import pytest

import orjson


def make_recursive_list_dict(limit: int, envelope_key: str, recurse_key: str):
    i = 0
    root = [{envelope_key: i, recurse_key: []}]
    i += 1
    while i < limit:
        sub = [{envelope_key: i, recurse_key: []}]
        sub[0][recurse_key] = root
        root = sub
        i += 1
    return root


class TestSerializeRecursion:
    @pytest.mark.parametrize("i", range(1, 127))
    def test_dumps_recursion_valid_long(self, i):
        root = make_recursive_list_dict(i, "🐈" * 512, "b" * 1024)
        orjson.dumps(root)

    @pytest.mark.parametrize("i", range(1, 127))
    def test_dumps_recursion_valid_short_1(self, i):
        root = make_recursive_list_dict(i, "a", "")
        orjson.dumps(root)

    @pytest.mark.parametrize("i", range(1, 127))
    def test_dumps_recursion_valid_short_2(self, i):
        root = make_recursive_list_dict(i, "level", "next")
        orjson.dumps(root)

    def test_dumps_recursion_limit(self):
        root = make_recursive_list_dict(128, "level", "next")
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(root)
