# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2025)

import orjson


def test_issue565():
    assert (
        orjson.dumps("\n\r\u000b\f\u001c\u001d\u001e")
        == b'"\\n\\r\\u000b\\f\\u001c\\u001d\\u001e"'
    )


def test_0x00():
    assert orjson.dumps("\u0000") == b'"\\u0000"'


def test_0x01():
    assert orjson.dumps("\u0001") == b'"\\u0001"'


def test_0x02():
    assert orjson.dumps("\u0002") == b'"\\u0002"'


def test_0x03():
    assert orjson.dumps("\u0003") == b'"\\u0003"'


def test_0x04():
    assert orjson.dumps("\u0004") == b'"\\u0004"'


def test_0x05():
    assert orjson.dumps("\u0005") == b'"\\u0005"'


def test_0x06():
    assert orjson.dumps("\u0006") == b'"\\u0006"'


def test_0x07():
    assert orjson.dumps("\u0007") == b'"\\u0007"'


def test_0x08():
    assert orjson.dumps("\u0008") == b'"\\b"'


def test_0x09():
    assert orjson.dumps("\u0009") == b'"\\t"'


def test_0x0a():
    assert orjson.dumps("\u000a") == b'"\\n"'


def test_0x0b():
    assert orjson.dumps("\u000b") == b'"\\u000b"'


def test_0x0c():
    assert orjson.dumps("\u000c") == b'"\\f"'


def test_0x0d():
    assert orjson.dumps("\u000d") == b'"\\r"'


def test_0x0e():
    assert orjson.dumps("\u000e") == b'"\\u000e"'


def test_0x0f():
    assert orjson.dumps("\u000f") == b'"\\u000f"'


def test_0x10():
    assert orjson.dumps("\u0010") == b'"\\u0010"'


def test_0x11():
    assert orjson.dumps("\u0011") == b'"\\u0011"'


def test_0x12():
    assert orjson.dumps("\u0012") == b'"\\u0012"'


def test_0x13():
    assert orjson.dumps("\u0013") == b'"\\u0013"'


def test_0x14():
    assert orjson.dumps("\u0014") == b'"\\u0014"'


def test_0x15():
    assert orjson.dumps("\u0015") == b'"\\u0015"'


def test_0x16():
    assert orjson.dumps("\u0016") == b'"\\u0016"'


def test_0x17():
    assert orjson.dumps("\u0017") == b'"\\u0017"'


def test_0x18():
    assert orjson.dumps("\u0018") == b'"\\u0018"'


def test_0x19():
    assert orjson.dumps("\u0019") == b'"\\u0019"'


def test_0x1a():
    assert orjson.dumps("\u001a") == b'"\\u001a"'


def test_backslash():
    assert orjson.dumps("\\") == b'"\\\\"'


def test_quote():
    assert orjson.dumps('"') == b'"\\""'
