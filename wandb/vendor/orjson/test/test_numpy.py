# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2020-2025), Ben Sully (2021), Nazar Kostetskyi (2022), Aviram Hassan (2020-2021), Marco Ribeiro (2020), Eric Jolibois (2021)
# mypy: ignore-errors

import sys

import pytest

import orjson

from .util import numpy


def numpy_default(obj):
    if isinstance(obj, numpy.ndarray):
        return obj.tolist()
    raise TypeError


@pytest.mark.skipif(numpy is None, reason="numpy is not installed")
class TestNumpy:
    def test_numpy_array_d1_uintp(self):
        low = numpy.iinfo(numpy.uintp).min
        high = numpy.iinfo(numpy.uintp).max
        assert orjson.dumps(
            numpy.array([low, high], numpy.uintp),
            option=orjson.OPT_SERIALIZE_NUMPY,
        ) == f"[{low},{high}]".encode("ascii")

    def test_numpy_array_d1_intp(self):
        low = numpy.iinfo(numpy.intp).min
        high = numpy.iinfo(numpy.intp).max
        assert orjson.dumps(
            numpy.array([low, high], numpy.intp),
            option=orjson.OPT_SERIALIZE_NUMPY,
        ) == f"[{low},{high}]".encode("ascii")

    def test_numpy_array_d1_i64(self):
        assert (
            orjson.dumps(
                numpy.array([-9223372036854775807, 9223372036854775807], numpy.int64),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[-9223372036854775807,9223372036854775807]"
        )

    def test_numpy_array_d1_u64(self):
        assert (
            orjson.dumps(
                numpy.array([0, 18446744073709551615], numpy.uint64),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[0,18446744073709551615]"
        )

    def test_numpy_array_d1_i8(self):
        assert (
            orjson.dumps(
                numpy.array([-128, 127], numpy.int8),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[-128,127]"
        )

    def test_numpy_array_d1_u8(self):
        assert (
            orjson.dumps(
                numpy.array([0, 255], numpy.uint8),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[0,255]"
        )

    def test_numpy_array_d1_i32(self):
        assert (
            orjson.dumps(
                numpy.array([-2147483647, 2147483647], numpy.int32),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[-2147483647,2147483647]"
        )

    def test_numpy_array_d1_i16(self):
        assert (
            orjson.dumps(
                numpy.array([-32768, 32767], numpy.int16),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[-32768,32767]"
        )

    def test_numpy_array_d1_u16(self):
        assert (
            orjson.dumps(
                numpy.array([0, 65535], numpy.uint16),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[0,65535]"
        )

    def test_numpy_array_d1_u32(self):
        assert (
            orjson.dumps(
                numpy.array([0, 4294967295], numpy.uint32),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[0,4294967295]"
        )

    def test_numpy_array_d1_f32(self):
        assert (
            orjson.dumps(
                numpy.array([1.0, 3.4028235e38], numpy.float32),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[1.0,3.4028235e38]"
        )

    def test_numpy_array_d1_f16(self):
        assert (
            orjson.dumps(
                numpy.array([-1.0, 0.0009765625, 1.0, 65504.0], numpy.float16),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[-1.0,0.0009765625,1.0,65504.0]"
        )

    def test_numpy_array_f16_roundtrip(self):
        ref = [
            -1.0,
            -2.0,
            0.000000059604645,
            0.000060975552,
            0.00006103515625,
            0.0009765625,
            0.33325195,
            0.99951172,
            1.0,
            1.00097656,
            65504.0,
        ]
        obj = numpy.array(ref, numpy.float16)  # type: ignore
        serialized = orjson.dumps(
            obj,
            option=orjson.OPT_SERIALIZE_NUMPY,
        )
        deserialized = numpy.array(orjson.loads(serialized), numpy.float16)  # type: ignore
        assert numpy.array_equal(obj, deserialized)

    def test_numpy_array_f16_edge(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.inf,
                        -numpy.inf,
                        numpy.nan,
                        -0.0,
                        0.0,
                        numpy.pi,
                    ],
                    numpy.float16,
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[null,null,null,-0.0,0.0,3.140625]"
        )

    def test_numpy_array_f32_edge(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.inf,
                        -numpy.inf,
                        numpy.nan,
                        -0.0,
                        0.0,
                        numpy.pi,
                    ],
                    numpy.float32,
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[null,null,null,-0.0,0.0,3.1415927]"
        )

    def test_numpy_array_f64_edge(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.inf,
                        -numpy.inf,
                        numpy.nan,
                        -0.0,
                        0.0,
                        numpy.pi,
                    ],
                    numpy.float64,
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[null,null,null,-0.0,0.0,3.141592653589793]"
        )

    def test_numpy_array_d1_f64(self):
        assert (
            orjson.dumps(
                numpy.array([1.0, 1.7976931348623157e308], numpy.float64),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[1.0,1.7976931348623157e308]"
        )

    def test_numpy_array_d1_bool(self):
        assert (
            orjson.dumps(
                numpy.array([True, False, False, True]),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[true,false,false,true]"
        )

    def test_numpy_array_d1_datetime64_years(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("1"),
                        numpy.datetime64("970"),
                        numpy.datetime64("1920"),
                        numpy.datetime64("1971"),
                        numpy.datetime64("2021"),
                        numpy.datetime64("2022"),
                        numpy.datetime64("2023"),
                        numpy.datetime64("9999"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["0001-01-01T00:00:00","0970-01-01T00:00:00","1920-01-01T00:00:00","1971-01-01T00:00:00","2021-01-01T00:00:00","2022-01-01T00:00:00","2023-01-01T00:00:00","9999-01-01T00:00:00"]'
        )

    def test_numpy_array_d1_datetime64_months(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01"),
                        numpy.datetime64("2022-01"),
                        numpy.datetime64("2023-01"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["2021-01-01T00:00:00","2022-01-01T00:00:00","2023-01-01T00:00:00"]'
        )

    def test_numpy_array_d1_datetime64_days(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01-01"),
                        numpy.datetime64("2021-01-01"),
                        numpy.datetime64("2021-01-01"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["2021-01-01T00:00:00","2021-01-01T00:00:00","2021-01-01T00:00:00"]'
        )

    def test_numpy_array_d1_datetime64_hours(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01-01T00"),
                        numpy.datetime64("2021-01-01T01"),
                        numpy.datetime64("2021-01-01T02"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["2021-01-01T00:00:00","2021-01-01T01:00:00","2021-01-01T02:00:00"]'
        )

    def test_numpy_array_d1_datetime64_minutes(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01-01T00:00"),
                        numpy.datetime64("2021-01-01T00:01"),
                        numpy.datetime64("2021-01-01T00:02"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["2021-01-01T00:00:00","2021-01-01T00:01:00","2021-01-01T00:02:00"]'
        )

    def test_numpy_array_d1_datetime64_seconds(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01-01T00:00:00"),
                        numpy.datetime64("2021-01-01T00:00:01"),
                        numpy.datetime64("2021-01-01T00:00:02"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["2021-01-01T00:00:00","2021-01-01T00:00:01","2021-01-01T00:00:02"]'
        )

    def test_numpy_array_d1_datetime64_milliseconds(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01-01T00:00:00"),
                        numpy.datetime64("2021-01-01T00:00:00.172"),
                        numpy.datetime64("2021-01-01T00:00:00.567"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["2021-01-01T00:00:00","2021-01-01T00:00:00.172000","2021-01-01T00:00:00.567000"]'
        )

    def test_numpy_array_d1_datetime64_microseconds(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01-01T00:00:00"),
                        numpy.datetime64("2021-01-01T00:00:00.172"),
                        numpy.datetime64("2021-01-01T00:00:00.567891"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["2021-01-01T00:00:00","2021-01-01T00:00:00.172000","2021-01-01T00:00:00.567891"]'
        )

    def test_numpy_array_d1_datetime64_nanoseconds(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01-01T00:00:00"),
                        numpy.datetime64("2021-01-01T00:00:00.172"),
                        numpy.datetime64("2021-01-01T00:00:00.567891234"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'["2021-01-01T00:00:00","2021-01-01T00:00:00.172000","2021-01-01T00:00:00.567891"]'
        )

    def test_numpy_array_d1_datetime64_picoseconds(self):
        try:
            orjson.dumps(
                numpy.array(
                    [
                        numpy.datetime64("2021-01-01T00:00:00"),
                        numpy.datetime64("2021-01-01T00:00:00.172"),
                        numpy.datetime64("2021-01-01T00:00:00.567891234567"),
                    ],
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            raise AssertionError()
        except TypeError as exc:
            assert str(exc) == "unsupported numpy.datetime64 unit: picoseconds"

    def test_numpy_array_d2_i64(self):
        assert (
            orjson.dumps(
                numpy.array([[1, 2, 3], [4, 5, 6]], numpy.int64),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[[1,2,3],[4,5,6]]"
        )

    def test_numpy_array_d2_f64(self):
        assert (
            orjson.dumps(
                numpy.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], numpy.float64),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[[1.0,2.0,3.0],[4.0,5.0,6.0]]"
        )

    def test_numpy_array_d3_i8(self):
        assert (
            orjson.dumps(
                numpy.array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]], numpy.int8),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[[[1,2],[3,4]],[[5,6],[7,8]]]"
        )

    def test_numpy_array_d3_u8(self):
        assert (
            orjson.dumps(
                numpy.array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]], numpy.uint8),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[[[1,2],[3,4]],[[5,6],[7,8]]]"
        )

    def test_numpy_array_d3_i32(self):
        assert (
            orjson.dumps(
                numpy.array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]], numpy.int32),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[[[1,2],[3,4]],[[5,6],[7,8]]]"
        )

    def test_numpy_array_d3_i64(self):
        assert (
            orjson.dumps(
                numpy.array([[[1, 2], [3, 4], [5, 6], [7, 8]]], numpy.int64),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[[[1,2],[3,4],[5,6],[7,8]]]"
        )

    def test_numpy_array_d3_f64(self):
        assert (
            orjson.dumps(
                numpy.array(
                    [[[1.0, 2.0], [3.0, 4.0]], [[5.0, 6.0], [7.0, 8.0]]],
                    numpy.float64,
                ),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"[[[1.0,2.0],[3.0,4.0]],[[5.0,6.0],[7.0,8.0]]]"
        )

    def test_numpy_array_fortran(self):
        array = numpy.array([[1, 2], [3, 4]], order="F")
        assert array.flags["F_CONTIGUOUS"] is True
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(array, option=orjson.OPT_SERIALIZE_NUMPY)
        assert orjson.dumps(
            array,
            default=numpy_default,
            option=orjson.OPT_SERIALIZE_NUMPY,
        ) == orjson.dumps(array.tolist())

    def test_numpy_array_non_contiguous_message(self):
        array = numpy.array([[1, 2], [3, 4]], order="F")
        assert array.flags["F_CONTIGUOUS"] is True
        try:
            orjson.dumps(array, option=orjson.OPT_SERIALIZE_NUMPY)
            raise AssertionError()
        except TypeError as exc:
            assert (
                str(exc)
                == "numpy array is not C contiguous; use ndarray.tolist() in default"
            )

    def test_numpy_array_unsupported_dtype(self):
        array = numpy.array([[1, 2], [3, 4]], numpy.csingle)  # type: ignore
        with pytest.raises(orjson.JSONEncodeError) as cm:
            orjson.dumps(array, option=orjson.OPT_SERIALIZE_NUMPY)
        assert "unsupported datatype in numpy array" in str(cm)

    def test_numpy_array_d1(self):
        array = numpy.array([1])
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

    def test_numpy_array_d2(self):
        array = numpy.array([[1]])
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

    def test_numpy_array_d3(self):
        array = numpy.array([[[1]]])
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

    def test_numpy_array_d4(self):
        array = numpy.array([[[[1]]]])
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

    def test_numpy_array_4_stride(self):
        array = numpy.random.rand(4, 4, 4, 4)
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

    def test_numpy_array_dimension_zero(self):
        array = numpy.array(0)
        assert array.ndim == 0
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(array, option=orjson.OPT_SERIALIZE_NUMPY)

        array = numpy.empty((0, 4, 2))
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

        array = numpy.empty((4, 0, 2))
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

        array = numpy.empty((2, 4, 0))
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

    def test_numpy_array_dimension_max(self):
        array = numpy.random.rand(
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        )
        assert array.ndim == 32
        assert (
            orjson.loads(
                orjson.dumps(
                    array,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                ),
            )
            == array.tolist()
        )

    def test_numpy_scalar_int8(self):
        assert orjson.dumps(numpy.int8(0), option=orjson.OPT_SERIALIZE_NUMPY) == b"0"
        assert (
            orjson.dumps(numpy.int8(127), option=orjson.OPT_SERIALIZE_NUMPY) == b"127"
        )
        assert (
            orjson.dumps(numpy.int8(-128), option=orjson.OPT_SERIALIZE_NUMPY) == b"-128"
        )

    def test_numpy_scalar_int16(self):
        assert orjson.dumps(numpy.int16(0), option=orjson.OPT_SERIALIZE_NUMPY) == b"0"
        assert (
            orjson.dumps(numpy.int16(32767), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"32767"
        )
        assert (
            orjson.dumps(numpy.int16(-32768), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"-32768"
        )

    def test_numpy_scalar_int32(self):
        assert orjson.dumps(numpy.int32(1), option=orjson.OPT_SERIALIZE_NUMPY) == b"1"
        assert (
            orjson.dumps(numpy.int32(2147483647), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"2147483647"
        )
        assert (
            orjson.dumps(numpy.int32(-2147483648), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"-2147483648"
        )

    def test_numpy_scalar_int64(self):
        assert (
            orjson.dumps(
                numpy.int64(-9223372036854775808),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"-9223372036854775808"
        )
        assert (
            orjson.dumps(
                numpy.int64(9223372036854775807),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"9223372036854775807"
        )

    def test_numpy_scalar_uint8(self):
        assert orjson.dumps(numpy.uint8(0), option=orjson.OPT_SERIALIZE_NUMPY) == b"0"
        assert (
            orjson.dumps(numpy.uint8(255), option=orjson.OPT_SERIALIZE_NUMPY) == b"255"
        )

    def test_numpy_scalar_uint16(self):
        assert orjson.dumps(numpy.uint16(0), option=orjson.OPT_SERIALIZE_NUMPY) == b"0"
        assert (
            orjson.dumps(numpy.uint16(65535), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"65535"
        )

    def test_numpy_scalar_uint32(self):
        assert orjson.dumps(numpy.uint32(0), option=orjson.OPT_SERIALIZE_NUMPY) == b"0"
        assert (
            orjson.dumps(numpy.uint32(4294967295), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"4294967295"
        )

    def test_numpy_scalar_uint64(self):
        assert orjson.dumps(numpy.uint64(0), option=orjson.OPT_SERIALIZE_NUMPY) == b"0"
        assert (
            orjson.dumps(
                numpy.uint64(18446744073709551615),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b"18446744073709551615"
        )

    def test_numpy_scalar_float16(self):
        assert (
            orjson.dumps(numpy.float16(1.0), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"1.0"
        )

    def test_numpy_scalar_float32(self):
        assert (
            orjson.dumps(numpy.float32(1.0), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"1.0"
        )

    def test_numpy_scalar_float64(self):
        assert (
            orjson.dumps(numpy.float64(123.123), option=orjson.OPT_SERIALIZE_NUMPY)
            == b"123.123"
        )

    def test_numpy_bool(self):
        assert (
            orjson.dumps(
                {"a": numpy.bool_(True), "b": numpy.bool_(False)},
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'{"a":true,"b":false}'
        )

    def test_numpy_datetime_year(self):
        assert (
            orjson.dumps(numpy.datetime64("2021"), option=orjson.OPT_SERIALIZE_NUMPY)
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_month(self):
        assert (
            orjson.dumps(numpy.datetime64("2021-01"), option=orjson.OPT_SERIALIZE_NUMPY)
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_day(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01"),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_hour(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00"),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_minute(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00"),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_second(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00"),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_milli(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172"),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'"2021-01-01T00:00:00.172000"'
        )

    def test_numpy_datetime_micro(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172576"),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'"2021-01-01T00:00:00.172576"'
        )

    def test_numpy_datetime_nano(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172576789"),
                option=orjson.OPT_SERIALIZE_NUMPY,
            )
            == b'"2021-01-01T00:00:00.172576"'
        )

    def test_numpy_datetime_naive_utc_year(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00+00:00"'
        )

    def test_numpy_datetime_naive_utc_month(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00+00:00"'
        )

    def test_numpy_datetime_naive_utc_day(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00+00:00"'
        )

    def test_numpy_datetime_naive_utc_hour(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00+00:00"'
        )

    def test_numpy_datetime_naive_utc_minute(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00+00:00"'
        )

    def test_numpy_datetime_naive_utc_second(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00+00:00"'
        )

    def test_numpy_datetime_naive_utc_milli(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00.172000+00:00"'
        )

    def test_numpy_datetime_naive_utc_micro(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172576"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00.172576+00:00"'
        )

    def test_numpy_datetime_naive_utc_nano(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172576789"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
            )
            == b'"2021-01-01T00:00:00.172576+00:00"'
        )

    def test_numpy_datetime_naive_utc_utc_z_year(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00Z"'
        )

    def test_numpy_datetime_naive_utc_utc_z_month(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00Z"'
        )

    def test_numpy_datetime_naive_utc_utc_z_day(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00Z"'
        )

    def test_numpy_datetime_naive_utc_utc_z_hour(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00Z"'
        )

    def test_numpy_datetime_naive_utc_utc_z_minute(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00Z"'
        )

    def test_numpy_datetime_naive_utc_utc_z_second(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00Z"'
        )

    def test_numpy_datetime_naive_utc_utc_z_milli(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00.172000Z"'
        )

    def test_numpy_datetime_naive_utc_utc_z_micro(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172576"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00.172576Z"'
        )

    def test_numpy_datetime_naive_utc_utc_z_nano(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172576789"),
                option=orjson.OPT_SERIALIZE_NUMPY
                | orjson.OPT_NAIVE_UTC
                | orjson.OPT_UTC_Z,
            )
            == b'"2021-01-01T00:00:00.172576Z"'
        )

    def test_numpy_datetime_omit_microseconds_year(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_omit_microseconds_month(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_omit_microseconds_day(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_omit_microseconds_hour(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_omit_microseconds_minute(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_omit_microseconds_second(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_omit_microseconds_milli(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_omit_microseconds_micro(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172576"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_omit_microseconds_nano(self):
        assert (
            orjson.dumps(
                numpy.datetime64("2021-01-01T00:00:00.172576789"),
                option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_OMIT_MICROSECONDS,
            )
            == b'"2021-01-01T00:00:00"'
        )

    def test_numpy_datetime_nat(self):
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(numpy.datetime64("NaT"), option=orjson.OPT_SERIALIZE_NUMPY)
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps([numpy.datetime64("NaT")], option=orjson.OPT_SERIALIZE_NUMPY)

    def test_numpy_repeated(self):
        data = numpy.array([[[1, 2], [3, 4], [5, 6], [7, 8]]], numpy.int64)  # type: ignore
        for _ in range(3):
            assert (
                orjson.dumps(
                    data,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                )
                == b"[[[1,2],[3,4],[5,6],[7,8]]]"
            )


@pytest.mark.skipif(numpy is None, reason="numpy is not installed")
class TestNumpyEquivalence:
    def _test(self, obj):
        assert orjson.dumps(obj, option=orjson.OPT_SERIALIZE_NUMPY) == orjson.dumps(
            obj.tolist(),
        )

    def test_numpy_uint8(self):
        self._test(numpy.array([0, 255], numpy.uint8))

    def test_numpy_uint16(self):
        self._test(numpy.array([0, 65535], numpy.uint16))

    def test_numpy_uint32(self):
        self._test(numpy.array([0, 4294967295], numpy.uint32))

    def test_numpy_uint64(self):
        self._test(numpy.array([0, 18446744073709551615], numpy.uint64))

    def test_numpy_int8(self):
        self._test(numpy.array([-128, 127], numpy.int8))

    def test_numpy_int16(self):
        self._test(numpy.array([-32768, 32767], numpy.int16))

    def test_numpy_int32(self):
        self._test(numpy.array([-2147483647, 2147483647], numpy.int32))

    def test_numpy_int64(self):
        self._test(
            numpy.array([-9223372036854775807, 9223372036854775807], numpy.int64),
        )

    @pytest.mark.skip(reason="tolist() conversion results in 3.4028234663852886e38")
    def test_numpy_float32(self):
        self._test(
            numpy.array(
                [
                    -340282346638528859811704183484516925440.0000000000000000,
                    340282346638528859811704183484516925440.0000000000000000,
                ],
                numpy.float32,
            ),
        )
        self._test(numpy.array([-3.4028235e38, 3.4028235e38], numpy.float32))

    def test_numpy_float64(self):
        self._test(
            numpy.array(
                [-1.7976931348623157e308, 1.7976931348623157e308],
                numpy.float64,
            ),
        )


@pytest.mark.skipif(numpy is None, reason="numpy is not installed")
class NumpyEndianness:
    def test_numpy_array_dimension_zero(self):
        wrong_endianness = ">" if sys.byteorder == "little" else "<"
        array = numpy.array([0, 1, 0.4, 5.7], dtype=f"{wrong_endianness}f8")
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(array, option=orjson.OPT_SERIALIZE_NUMPY)
