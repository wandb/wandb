# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2020-2025)

import dataclasses
import datetime
import uuid

import pytest

import orjson

try:
    import pytz
except ImportError:
    pytz = None  # type: ignore

from .util import numpy


class SubStr(str):
    pass


class TestNonStrKeyTests:
    def test_dict_keys_duplicate(self):
        """
        OPT_NON_STR_KEYS serializes duplicate keys
        """
        assert (
            orjson.dumps({"1": True, 1: False}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"1":true,"1":false}'
        )

    def test_dict_keys_int(self):
        assert (
            orjson.dumps({1: True, 2: False}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"1":true,"2":false}'
        )

    def test_dict_keys_substr(self):
        assert (
            orjson.dumps({SubStr("aaa"): True}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"aaa":true}'
        )

    def test_dict_keys_substr_passthrough(self):
        """
        OPT_PASSTHROUGH_SUBCLASS does not affect OPT_NON_STR_KEYS
        """
        assert (
            orjson.dumps(
                {SubStr("aaa"): True},
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_PASSTHROUGH_SUBCLASS,
            )
            == b'{"aaa":true}'
        )

    def test_dict_keys_substr_invalid(self):
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps({SubStr("\ud800"): True}, option=orjson.OPT_NON_STR_KEYS)

    def test_dict_keys_strict(self):
        """
        OPT_NON_STR_KEYS does not respect OPT_STRICT_INTEGER
        """
        assert (
            orjson.dumps(
                {9223372036854775807: True},
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_STRICT_INTEGER,
            )
            == b'{"9223372036854775807":true}'
        )

    def test_dict_keys_int_range_valid_i64(self):
        """
        OPT_NON_STR_KEYS has a i64 range for int, valid
        """
        assert (
            orjson.dumps(
                {9223372036854775807: True},
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_STRICT_INTEGER,
            )
            == b'{"9223372036854775807":true}'
        )
        assert (
            orjson.dumps(
                {-9223372036854775807: True},
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_STRICT_INTEGER,
            )
            == b'{"-9223372036854775807":true}'
        )
        assert (
            orjson.dumps(
                {9223372036854775809: True},
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_STRICT_INTEGER,
            )
            == b'{"9223372036854775809":true}'
        )

    def test_dict_keys_int_range_valid_u64(self):
        """
        OPT_NON_STR_KEYS has a u64 range for int, valid
        """
        assert (
            orjson.dumps(
                {0: True},
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_STRICT_INTEGER,
            )
            == b'{"0":true}'
        )
        assert (
            orjson.dumps(
                {18446744073709551615: True},
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_STRICT_INTEGER,
            )
            == b'{"18446744073709551615":true}'
        )

    def test_dict_keys_int_range_invalid(self):
        """
        OPT_NON_STR_KEYS has a range of i64::MIN to u64::MAX
        """
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps({-9223372036854775809: True}, option=orjson.OPT_NON_STR_KEYS)
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps({18446744073709551616: True}, option=orjson.OPT_NON_STR_KEYS)

    def test_dict_keys_float(self):
        assert (
            orjson.dumps({1.1: True, 2.2: False}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"1.1":true,"2.2":false}'
        )

    def test_dict_keys_inf(self):
        assert (
            orjson.dumps({float("Infinity"): True}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"null":true}'
        )
        assert (
            orjson.dumps({float("-Infinity"): True}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"null":true}'
        )

    def test_dict_keys_nan(self):
        assert (
            orjson.dumps({float("NaN"): True}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"null":true}'
        )

    def test_dict_keys_bool(self):
        assert (
            orjson.dumps({True: True, False: False}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"true":true,"false":false}'
        )

    def test_dict_keys_datetime(self):
        assert (
            orjson.dumps(
                {datetime.datetime(2000, 1, 1, 2, 3, 4, 123): True},
                option=orjson.OPT_NON_STR_KEYS,
            )
            == b'{"2000-01-01T02:03:04.000123":true}'
        )

    def test_dict_keys_datetime_opt(self):
        assert (
            orjson.dumps(
                {datetime.datetime(2000, 1, 1, 2, 3, 4, 123): True},
                option=orjson.OPT_NON_STR_KEYS
                | orjson.OPT_OMIT_MICROSECONDS
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'{"2000-01-01T02:03:04Z":true}'
        )

    def test_dict_keys_datetime_passthrough(self):
        """
        OPT_PASSTHROUGH_DATETIME does not affect OPT_NON_STR_KEYS
        """
        assert (
            orjson.dumps(
                {datetime.datetime(2000, 1, 1, 2, 3, 4, 123): True},
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_PASSTHROUGH_DATETIME,
            )
            == b'{"2000-01-01T02:03:04.000123":true}'
        )

    def test_dict_keys_uuid(self):
        """
        OPT_NON_STR_KEYS always serializes UUID as keys
        """
        assert (
            orjson.dumps(
                {uuid.UUID("7202d115-7ff3-4c81-a7c1-2a1f067b1ece"): True},
                option=orjson.OPT_NON_STR_KEYS,
            )
            == b'{"7202d115-7ff3-4c81-a7c1-2a1f067b1ece":true}'
        )

    def test_dict_keys_date(self):
        assert (
            orjson.dumps(
                {datetime.date(1970, 1, 1): True},
                option=orjson.OPT_NON_STR_KEYS,
            )
            == b'{"1970-01-01":true}'
        )

    def test_dict_keys_time(self):
        assert (
            orjson.dumps(
                {datetime.time(12, 15, 59, 111): True},
                option=orjson.OPT_NON_STR_KEYS,
            )
            == b'{"12:15:59.000111":true}'
        )

    def test_dict_non_str_and_sort_keys(self):
        assert (
            orjson.dumps(
                {
                    "other": 1,
                    datetime.date(1970, 1, 5): 2,
                    datetime.date(1970, 1, 3): 3,
                },
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SORT_KEYS,
            )
            == b'{"1970-01-03":3,"1970-01-05":2,"other":1}'
        )

    @pytest.mark.skipif(pytz is None, reason="pytz optional")
    def test_dict_keys_time_err(self):
        """
        OPT_NON_STR_KEYS propagates errors in types
        """
        val = datetime.time(12, 15, 59, 111, tzinfo=pytz.timezone("Asia/Shanghai"))
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps({val: True}, option=orjson.OPT_NON_STR_KEYS)

    def test_dict_keys_str(self):
        assert (
            orjson.dumps({"1": True}, option=orjson.OPT_NON_STR_KEYS) == b'{"1":true}'
        )

    def test_dict_keys_type(self):
        class Obj:
            a: str

        val = Obj()
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps({val: True}, option=orjson.OPT_NON_STR_KEYS)

    @pytest.mark.skipif(numpy is None, reason="numpy is not installed")
    def test_dict_keys_array(self):
        with pytest.raises(TypeError):
            _ = {numpy.array([1, 2]): True}  # type: ignore

    def test_dict_keys_dataclass(self):
        @dataclasses.dataclass
        class Dataclass:
            a: str

        with pytest.raises(TypeError):
            _ = {Dataclass("a"): True}

    def test_dict_keys_dataclass_hash(self):
        @dataclasses.dataclass
        class Dataclass:
            a: str

            def __hash__(self):
                return 1

        obj = {Dataclass("a"): True}
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS)

    def test_dict_keys_list(self):
        with pytest.raises(TypeError):
            _ = {[]: True}

    def test_dict_keys_dict(self):
        with pytest.raises(TypeError):
            _ = {{}: True}

    def test_dict_keys_tuple(self):
        obj = {(): True}
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS)

    def test_dict_keys_unknown(self):
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps({frozenset(): True}, option=orjson.OPT_NON_STR_KEYS)

    def test_dict_keys_no_str_call(self):
        class Obj:
            a: str

            def __str__(self):
                return "Obj"

        val = Obj()
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps({val: True}, option=orjson.OPT_NON_STR_KEYS)
