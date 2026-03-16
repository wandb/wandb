# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2019-2025), Rami Chowdhury (2020), Marc Mueller (2023), Jack Amadeo (2023)

import datetime
import sys
import uuid

import pytest

import orjson

from .util import SUPPORTS_GETREFCOUNT, numpy


class Custom:
    def __init__(self):
        self.name = uuid.uuid4().hex

    def __str__(self):
        return f"{self.__class__.__name__}({self.name})"


class Recursive:
    def __init__(self, cur):
        self.cur = cur


def default_recursive(obj):
    if obj.cur != 0:
        obj.cur -= 1
        return obj
    return obj.cur


def default_raises(obj):
    raise TypeError


class TestType:
    def test_default_not_callable(self):
        """
        dumps() default not callable
        """
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(Custom(), default=NotImplementedError)

        ran = False
        try:
            orjson.dumps(Custom(), default=NotImplementedError)
        except Exception as err:
            assert isinstance(err, orjson.JSONEncodeError)
            assert str(err) == "default serializer exceeds recursion limit"
            ran = True
        assert ran

    def test_default_func(self):
        """
        dumps() default function
        """
        ref = Custom()

        def default(obj):
            return str(obj)

        assert orjson.dumps(ref, default=default) == b'"%s"' % str(ref).encode("utf-8")

    def test_default_func_none(self):
        """
        dumps() default function None ok
        """
        assert orjson.dumps(Custom(), default=lambda x: None) == b"null"

    def test_default_func_empty(self):
        """
        dumps() default function no explicit return
        """
        ref = Custom()

        def default(obj):
            if isinstance(obj, set):
                return list(obj)

        assert orjson.dumps(ref, default=default) == b"null"
        assert orjson.dumps({ref}, default=default) == b"[null]"

    def test_default_func_exc(self):
        """
        dumps() default function raises exception
        """

        def default(obj):
            raise NotImplementedError

        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(Custom(), default=default)

        ran = False
        try:
            orjson.dumps(Custom(), default=default)
        except Exception as err:
            assert isinstance(err, orjson.JSONEncodeError)
            assert str(err) == "Type is not JSON serializable: Custom"
            ran = True
        assert ran

    def test_default_exception_type(self):
        """
        dumps() TypeError in default() raises orjson.JSONEncodeError
        """
        ref = Custom()

        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(ref, default=default_raises)

    def test_default_vectorcall_str(self):
        """
        dumps() default function vectorcall str
        """

        class SubStr(str):
            pass

        obj = SubStr("saasa")
        ref = b'"%s"' % str(obj).encode("utf-8")
        assert (
            orjson.dumps(obj, option=orjson.OPT_PASSTHROUGH_SUBCLASS, default=str)
            == ref
        )

    def test_default_vectorcall_list(self):
        """
        dumps() default function vectorcall list
        """
        obj = {1, 2}
        ref = b"[1,2]"
        assert orjson.dumps(obj, default=list) == ref

    def test_default_func_nested_str(self):
        """
        dumps() default function nested str
        """
        ref = Custom()

        def default(obj):
            return str(obj)

        assert orjson.dumps({"a": ref}, default=default) == b'{"a":"%s"}' % str(
            ref,
        ).encode("utf-8")

    def test_default_func_list(self):
        """
        dumps() default function nested list
        """
        ref = Custom()

        def default(obj):
            if isinstance(obj, Custom):
                return [str(obj)]

        assert orjson.dumps({"a": ref}, default=default) == b'{"a":["%s"]}' % str(
            ref,
        ).encode("utf-8")

    def test_default_func_nested_list(self):
        """
        dumps() default function list
        """
        ref = Custom()

        def default(obj):
            return str(obj)

        assert orjson.dumps([ref] * 100, default=default) == b"[%s]" % b",".join(
            b'"%s"' % str(ref).encode("utf-8") for _ in range(100)
        )

    def test_default_func_bytes(self):
        """
        dumps() default function errors on non-str
        """
        ref = Custom()

        def default(obj):
            return bytes(obj)

        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(ref, default=default)

        ran = False
        try:
            orjson.dumps(ref, default=default)
        except Exception as err:
            assert isinstance(err, orjson.JSONEncodeError)
            assert str(err) == "Type is not JSON serializable: Custom"
            ran = True
        assert ran

    def test_default_func_invalid_str(self):
        """
        dumps() default function errors on invalid str
        """
        ref = Custom()

        def default(obj):
            return "\ud800"

        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(ref, default=default)

    def test_default_lambda_ok(self):
        """
        dumps() default lambda
        """
        ref = Custom()
        assert orjson.dumps(ref, default=lambda x: str(x)) == b'"%s"' % str(ref).encode(
            "utf-8",
        )

    def test_default_callable_ok(self):
        """
        dumps() default callable
        """

        class CustomSerializer:
            def __init__(self):
                self._cache = {}

            def __call__(self, obj):
                if obj not in self._cache:
                    self._cache[obj] = str(obj)
                return self._cache[obj]

        ref_obj = Custom()
        ref_bytes = b'"%s"' % str(ref_obj).encode("utf-8")
        for obj in [ref_obj] * 100:
            assert orjson.dumps(obj, default=CustomSerializer()) == ref_bytes

    def test_default_recursion(self):
        """
        dumps() default recursion limit
        """
        assert orjson.dumps(Recursive(254), default=default_recursive) == b"0"

    def test_default_recursion_reset(self):
        """
        dumps() default recursion limit reset
        """
        assert (
            orjson.dumps(
                [Recursive(254), {"a": "b"}, Recursive(254), Recursive(254)],
                default=default_recursive,
            )
            == b'[0,{"a":"b"},0,0]'
        )

    def test_default_recursion_infinite(self):
        """
        dumps() default infinite recursion
        """
        ref = Custom()

        def default(obj):
            return obj

        if SUPPORTS_GETREFCOUNT:
            refcount = sys.getrefcount(ref)
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(ref, default=default)
        if SUPPORTS_GETREFCOUNT:
            assert sys.getrefcount(ref) == refcount

    def test_reference_cleanup_default_custom_pass(self):
        ref = Custom()

        def default(obj):
            if isinstance(ref, Custom):
                return str(ref)
            raise TypeError

        if SUPPORTS_GETREFCOUNT:
            refcount = sys.getrefcount(ref)
        orjson.dumps(ref, default=default)
        if SUPPORTS_GETREFCOUNT:
            assert sys.getrefcount(ref) == refcount

    def test_reference_cleanup_default_custom_error(self):
        """
        references to encoded objects are cleaned up
        """
        ref = Custom()

        def default(obj):
            raise TypeError

        if SUPPORTS_GETREFCOUNT:
            refcount = sys.getrefcount(ref)
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(ref, default=default)
        if SUPPORTS_GETREFCOUNT:
            assert sys.getrefcount(ref) == refcount

    def test_reference_cleanup_default_subclass(self):
        ref = datetime.datetime(1970, 1, 1, 0, 0, 0)

        def default(obj):
            if isinstance(ref, datetime.datetime):
                return repr(ref)
            raise TypeError

        if SUPPORTS_GETREFCOUNT:
            refcount = sys.getrefcount(ref)
        orjson.dumps(ref, option=orjson.OPT_PASSTHROUGH_DATETIME, default=default)
        if SUPPORTS_GETREFCOUNT:
            assert sys.getrefcount(ref) == refcount

    def test_reference_cleanup_default_subclass_lambda(self):
        ref = uuid.uuid4()

        if SUPPORTS_GETREFCOUNT:
            refcount = sys.getrefcount(ref)
        orjson.dumps(
            ref,
            option=orjson.OPT_PASSTHROUGH_DATETIME,
            default=lambda val: str(val),
        )
        if SUPPORTS_GETREFCOUNT:
            assert sys.getrefcount(ref) == refcount

    @pytest.mark.skipif(numpy is None, reason="numpy is not installed")
    def test_default_numpy(self):
        ref = numpy.array([""] * 100)  # type: ignore
        if SUPPORTS_GETREFCOUNT:
            refcount = sys.getrefcount(ref)
        orjson.dumps(
            ref,
            option=orjson.OPT_SERIALIZE_NUMPY,
            default=lambda val: val.tolist(),
        )
        if SUPPORTS_GETREFCOUNT:
            assert sys.getrefcount(ref) == refcount

    def test_default_set(self):
        """
        dumps() default function with set
        """

        def default(obj):
            if isinstance(obj, set):
                return list(obj)
            raise TypeError

        assert orjson.dumps({1, 2}, default=default) == b"[1,2]"
