# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2020-2025)

import datetime
import enum

import pytest

import orjson


class StrEnum(str, enum.Enum):
    AAA = "aaa"


class IntEnum(int, enum.Enum):
    ONE = 1


class IntEnumEnum(enum.IntEnum):
    ONE = 1


class IntFlagEnum(enum.IntFlag):
    ONE = 1


class FlagEnum(enum.Flag):
    ONE = 1


class AutoEnum(enum.auto):
    A = "a"


class FloatEnum(float, enum.Enum):
    ONE = 1.1


class Custom:
    def __init__(self, val):
        self.val = val


def default(obj):
    if isinstance(obj, Custom):
        return obj.val
    raise TypeError


class UnspecifiedEnum(enum.Enum):
    A = "a"
    B = 1
    C = FloatEnum.ONE
    D = {"d": IntEnum.ONE}  # noqa: RUF012
    E = Custom("c")
    F = datetime.datetime(1970, 1, 1)


class TestEnum:
    def test_cannot_subclass(self):
        """
        enum.Enum cannot be subclassed

        obj->ob_type->ob_base will always be enum.EnumMeta
        """
        with pytest.raises(TypeError):

            class Subclass(StrEnum):  # type: ignore
                B = "b"

    def test_arbitrary_enum(self):
        assert orjson.dumps(UnspecifiedEnum.A) == b'"a"'
        assert orjson.dumps(UnspecifiedEnum.B) == b"1"
        assert orjson.dumps(UnspecifiedEnum.C) == b"1.1"
        assert orjson.dumps(UnspecifiedEnum.D) == b'{"d":1}'

    def test_custom_enum(self):
        assert orjson.dumps(UnspecifiedEnum.E, default=default) == b'"c"'

    def test_enum_options(self):
        assert (
            orjson.dumps(UnspecifiedEnum.F, option=orjson.OPT_NAIVE_UTC)
            == b'"1970-01-01T00:00:00+00:00"'
        )

    def test_int_enum(self):
        assert orjson.dumps(IntEnum.ONE) == b"1"

    def test_intenum_enum(self):
        assert orjson.dumps(IntEnumEnum.ONE) == b"1"

    def test_intflag_enum(self):
        assert orjson.dumps(IntFlagEnum.ONE) == b"1"

    def test_flag_enum(self):
        assert orjson.dumps(FlagEnum.ONE) == b"1"

    def test_auto_enum(self):
        assert orjson.dumps(AutoEnum.A) == b'"a"'

    def test_float_enum(self):
        assert orjson.dumps(FloatEnum.ONE) == b"1.1"

    def test_str_enum(self):
        assert orjson.dumps(StrEnum.AAA) == b'"aaa"'

    def test_bool_enum(self):
        with pytest.raises(TypeError):

            class BoolEnum(bool, enum.Enum):  # type: ignore
                TRUE = True

    def test_non_str_keys_enum(self):
        assert (
            orjson.dumps({StrEnum.AAA: 1}, option=orjson.OPT_NON_STR_KEYS)
            == b'{"aaa":1}'
        )
        assert (
            orjson.dumps({IntEnum.ONE: 1}, option=orjson.OPT_NON_STR_KEYS) == b'{"1":1}'
        )
