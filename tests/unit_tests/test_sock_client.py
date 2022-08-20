import pytest
from wandb.sdk.lib import sock_client


def test_append():
    buffer = sock_client.SockBuffer()
    data1 = b"1234"
    buffer.put(data1, len(data1))
    assert buffer.length == 4
    data2 = b"123456"
    buffer.put(data2, len(data2))
    assert buffer.length == 10


def test_peek():
    buffer = sock_client.SockBuffer()
    data1 = b"123456"
    buffer.put(data1, len(data1))
    assert buffer.length == 6
    assert buffer.peek(2, 5) == b"345"
    assert buffer.length == 6


def test_get():
    buffer = sock_client.SockBuffer()
    data1 = b"0123456"
    buffer.put(data1, len(data1))
    assert buffer.length == 7
    assert buffer.get(1, 3) == b"12"
    assert buffer.length == 4


def test_peek_get():
    buffer = sock_client.SockBuffer()
    data1 = b"0123456"
    buffer.put(data1, len(data1))
    assert buffer.length == 7
    assert buffer.peek(2, 5) == b"234"
    assert buffer.length == 7
    assert buffer.get(3, 6) == b"345"
    assert buffer.length == 1


def test_get_cross():
    buffer = sock_client.SockBuffer()
    data1 = b"0123456"
    buffer.put(data1, len(data1))
    data2 = b"abcde"
    buffer.put(data2, len(data2))
    assert buffer.length == 12
    assert buffer.get(4, 9) == b"456ab"
    assert buffer.length == 3
    assert buffer.get(0, 1) == b"c"
    assert buffer.length == 2


def test_get_cross_two():
    buffer = sock_client.SockBuffer()
    data1 = b"0123456"
    buffer.put(data1, len(data1))
    data2 = b"abcde"
    buffer.put(data2, len(data2))
    data3 = b"ABCDEFG"
    buffer.put(data3, len(data3))
    assert buffer.length == 19
    assert buffer.get(4, 14) == b"456abcdeAB"
    assert buffer.length == 5


def test_get_partial():
    buffer = sock_client.SockBuffer()
    data1 = b"012345678"
    buffer.put(data1, len(data1))
    data2 = b"abcdef"
    buffer.put(data2, len(data2))
    assert buffer.length == 15
    assert buffer.get(2, 5) == b"234"
    assert buffer.length == 10
    assert buffer.get(1, 4) == b"678"


def test_get_index_error():
    buffer = sock_client.SockBuffer()
    data1 = b"0123456"
    buffer.put(data1, len(data1))
    assert buffer.length == 7
    with pytest.raises(IndexError):
        buffer.get(3, 8)
