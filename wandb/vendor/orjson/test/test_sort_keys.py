# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2020-2025)

import orjson

from .util import needs_data, read_fixture_obj


@needs_data
class TestDictSortKeys:
    # citm_catalog is already sorted
    def test_twitter_sorted(self):
        """
        twitter.json sorted
        """
        obj = read_fixture_obj("twitter.json.xz")
        assert list(obj.keys()) != sorted(list(obj.keys()))
        serialized = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
        val = orjson.loads(serialized)
        assert list(val.keys()) == sorted(list(val.keys()))

    def test_canada_sorted(self):
        """
        canada.json sorted
        """
        obj = read_fixture_obj("canada.json.xz")
        assert list(obj.keys()) != sorted(list(obj.keys()))
        serialized = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
        val = orjson.loads(serialized)
        assert list(val.keys()) == sorted(list(val.keys()))

    def test_github_sorted(self):
        """
        github.json sorted
        """
        obj = read_fixture_obj("github.json.xz")
        for each in obj:
            assert list(each.keys()) != sorted(list(each.keys()))
        serialized = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
        val = orjson.loads(serialized)
        for each in val:
            assert list(each.keys()) == sorted(list(each.keys()))

    def test_utf8_sorted(self):
        """
        UTF-8 sorted
        """
        obj = {"a": 1, "ä": 2, "A": 3}
        assert list(obj.keys()) != sorted(list(obj.keys()))
        serialized = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
        val = orjson.loads(serialized)
        assert list(val.keys()) == sorted(list(val.keys()))
