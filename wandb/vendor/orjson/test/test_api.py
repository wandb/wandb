# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2018-2025), hauntsaninja (2020)

import datetime
import inspect
import json
import re

import pytest

import orjson

SIMPLE_TYPES = (1, 1.0, -1, None, "str", True, False)

LOADS_RECURSION_LIMIT = 1024


def default(obj):
    return str(obj)


class TestApi:
    def test_loads_trailing(self):
        """
        loads() handles trailing whitespace
        """
        assert orjson.loads("{}\n\t ") == {}

    def test_loads_trailing_invalid(self):
        """
        loads() handles trailing invalid
        """
        pytest.raises(orjson.JSONDecodeError, orjson.loads, "{}\n\t a")

    def test_simple_json(self):
        """
        dumps() equivalent to json on simple types
        """
        for obj in SIMPLE_TYPES:
            assert orjson.dumps(obj) == json.dumps(obj).encode("utf-8")

    def test_simple_round_trip(self):
        """
        dumps(), loads() round trip on simple types
        """
        for obj in SIMPLE_TYPES:
            assert orjson.loads(orjson.dumps(obj)) == obj

    def test_loads_type(self):
        """
        loads() invalid type
        """
        for val in (1, 3.14, [], {}, None):  # type: ignore
            pytest.raises(orjson.JSONDecodeError, orjson.loads, val)

    def test_loads_recursion_partial(self):
        """
        loads() recursion limit partial
        """
        pytest.raises(orjson.JSONDecodeError, orjson.loads, "[" * (1024 * 1024))

    def test_loads_recursion_valid_limit_array(self):
        """
        loads() recursion limit at limit array
        """
        n = LOADS_RECURSION_LIMIT + 1
        value = b"[" * n + b"]" * n
        pytest.raises(orjson.JSONDecodeError, orjson.loads, value)

    def test_loads_recursion_valid_limit_object(self):
        """
        loads() recursion limit at limit object
        """
        n = LOADS_RECURSION_LIMIT
        value = b'{"key":' * n + b'{"key":true}' + b"}" * n
        pytest.raises(orjson.JSONDecodeError, orjson.loads, value)

    def test_loads_recursion_valid_limit_mixed(self):
        """
        loads() recursion limit at limit mixed
        """
        n = LOADS_RECURSION_LIMIT
        value = b"".join((b"[", b'{"key":' * n, b'{"key":true}' + b"}" * n, b"]"))
        pytest.raises(orjson.JSONDecodeError, orjson.loads, value)

    def test_loads_recursion_valid_excessive_array(self):
        """
        loads() recursion limit excessively high value
        """
        n = 10000000
        value = b"[" * n + b"]" * n
        pytest.raises(orjson.JSONDecodeError, orjson.loads, value)

    def test_loads_recursion_valid_limit_array_pretty(self):
        """
        loads() recursion limit at limit array pretty
        """
        n = LOADS_RECURSION_LIMIT + 1
        value = b"[\n  " * n + b"]" * n
        pytest.raises(orjson.JSONDecodeError, orjson.loads, value)

    def test_loads_recursion_valid_limit_object_pretty(self):
        """
        loads() recursion limit at limit object pretty
        """
        n = LOADS_RECURSION_LIMIT
        value = b'{\n  "key":' * n + b'{"key":true}' + b"}" * n
        pytest.raises(orjson.JSONDecodeError, orjson.loads, value)

    def test_loads_recursion_valid_limit_mixed_pretty(self):
        """
        loads() recursion limit at limit mixed pretty
        """
        n = LOADS_RECURSION_LIMIT
        value = b'[\n  {"key":' * n + b'{"key":true}' + b"}" * n + b"]"
        pytest.raises(orjson.JSONDecodeError, orjson.loads, value)

    def test_loads_recursion_valid_excessive_array_pretty(self):
        """
        loads() recursion limit excessively high value pretty
        """
        n = 10000000
        value = b"[\n  " * n + b"]" * n
        pytest.raises(orjson.JSONDecodeError, orjson.loads, value)

    def test_version(self):
        """
        __version__
        """
        assert re.match(r"^\d+\.\d+(\.\d+)?$", orjson.__version__)

    def test_valueerror(self):
        """
        orjson.JSONDecodeError is a subclass of ValueError
        """
        pytest.raises(orjson.JSONDecodeError, orjson.loads, "{")
        pytest.raises(ValueError, orjson.loads, "{")

    def test_optional_none(self):
        """
        dumps() option, default None
        """
        assert orjson.dumps([], option=None) == b"[]"
        assert orjson.dumps([], default=None) == b"[]"
        assert orjson.dumps([], option=None, default=None) == b"[]"
        assert orjson.dumps([], None, None) == b"[]"

    def test_option_not_int(self):
        """
        dumps() option not int or None
        """
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(True, option=True)

    def test_option_invalid_int(self):
        """
        dumps() option invalid 64-bit number
        """
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(True, option=9223372036854775809)

    def test_option_range_low(self):
        """
        dumps() option out of range low
        """
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(True, option=-1)

    def test_option_range_high(self):
        """
        dumps() option out of range high
        """
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(True, option=1 << 13)

    def test_opts_multiple(self):
        """
        dumps() multiple option
        """
        assert (
            orjson.dumps(
                [1, datetime.datetime(2000, 1, 1, 2, 3, 4)],
                option=orjson.OPT_STRICT_INTEGER | orjson.OPT_NAIVE_UTC,
            )
            == b'[1,"2000-01-01T02:03:04+00:00"]'
        )

    def test_default_positional(self):
        """
        dumps() positional arg
        """
        with pytest.raises(TypeError):
            orjson.dumps(__obj={})  # type: ignore
        with pytest.raises(TypeError):
            orjson.dumps(zxc={})  # type: ignore

    def test_default_unknown_kwarg(self):
        """
        dumps() unknown kwarg
        """
        with pytest.raises(TypeError):
            orjson.dumps({}, zxc=default)  # type: ignore

    def test_default_empty_kwarg(self):
        """
        dumps() empty kwarg
        """
        assert orjson.dumps(None) == b"null"

    def test_default_twice(self):
        """
        dumps() default twice
        """
        with pytest.raises(TypeError):
            orjson.dumps({}, default, default=default)  # type: ignore

    def test_option_twice(self):
        """
        dumps() option twice
        """
        with pytest.raises(TypeError):
            orjson.dumps({}, None, orjson.OPT_NAIVE_UTC, option=orjson.OPT_NAIVE_UTC)  # type: ignore

    def test_option_mixed(self):
        """
        dumps() option one arg, one kwarg
        """

        class Custom:
            def __str__(self):
                return "zxc"

        assert (
            orjson.dumps(
                [Custom(), datetime.datetime(2000, 1, 1, 2, 3, 4)],
                default,
                option=orjson.OPT_NAIVE_UTC,
            )
            == b'["zxc","2000-01-01T02:03:04+00:00"]'
        )

    def test_dumps_signature(self):
        """
        dumps() valid __text_signature__
        """
        assert (
            str(inspect.signature(orjson.dumps))
            == "(obj, /, default=None, option=None)"
        )
        inspect.signature(orjson.dumps).bind("str")
        inspect.signature(orjson.dumps).bind("str", default=default, option=1)
        inspect.signature(orjson.dumps).bind("str", default=None, option=None)

    def test_loads_signature(self):
        """
        loads() valid __text_signature__
        """
        assert str(inspect.signature(orjson.loads)), "(obj == /)"
        inspect.signature(orjson.loads).bind("[]")

    def test_dumps_module_str(self):
        """
        orjson.dumps.__module__ is a str
        """
        assert orjson.dumps.__module__ == "orjson"

    def test_loads_module_str(self):
        """
        orjson.loads.__module__ is a str
        """
        assert orjson.loads.__module__ == "orjson"

    def test_bytes_buffer(self):
        """
        dumps() trigger buffer growing where length is greater than growth
        """
        a = "a" * 900
        b = "b" * 4096
        c = "c" * 4096 * 4096
        assert orjson.dumps([a, b, c]) == f'["{a}","{b}","{c}"]'.encode("utf-8")

    def test_bytes_null_terminated(self):
        """
        dumps() PyBytesObject buffer is null-terminated
        """
        # would raise ValueError: invalid literal for int() with base 10: b'1596728892'
        int(orjson.dumps(1596728892))
