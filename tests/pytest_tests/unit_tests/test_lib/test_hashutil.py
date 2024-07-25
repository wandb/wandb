import base64
import hashlib
from typing import Optional

from hypothesis import example, given, settings
from hypothesis import strategies as st
from wandb.sdk.lib import hashutil


def test_md5_string():
    assert hashutil.md5_string("") == "1B2M2Y8AsgTpgAmY7PhCfg=="
    assert hashutil.md5_string("foo") == "rL0Y20zC+Fzt72VPzMSk2A=="


def write_file(
    filename: str,
    mode: str,
    content,
    encoding: Optional[str] = None,
) -> None:
    with open(filename, mode, encoding=encoding) as f:
        f.write(content)


def read_file(filename: str, mode: str) -> bytes:
    with open(filename, mode) as f:
        return f.read()


@given(st.binary())
def test_hex_to_b64_id(data):
    hex_str = data.hex()
    assert hashutil.hex_to_b64_id(hex_str) == base64.b64encode(data).decode("ascii")


@given(st.binary())
def test_hex_to_b64_id_bytes(data):
    hex_bytes = data.hex().encode("ascii")
    assert hashutil.hex_to_b64_id(hex_bytes) == base64.b64encode(data).decode("ascii")


@given(st.binary())
def test_b64_to_hex_id(data):
    b64str = base64.b64encode(data).decode("ascii")
    assert hashutil.b64_to_hex_id(b64str) == data.hex()


@given(st.binary())
def test_b64_to_hex_id_bytes(data):
    b64 = base64.b64encode(data)
    assert hashutil.b64_to_hex_id(b64) == data.hex()


def test_md5_file_b64_no_files():
    b64hash = base64.b64encode(hashlib.md5(b"").digest()).decode("ascii")
    assert b64hash == hashutil.md5_file_b64()


@given(st.binary())
def test_md5_file_hex_single_file(data):
    write_file("binfile", "wb", data)
    assert hashlib.md5(data).hexdigest() == hashutil.md5_file_hex("binfile")


@given(st.binary(), st.text(), st.binary())
@settings(max_examples=10)
@example(b"g", "", b"\xb6DZ")
@example(b"\x1b\xb7", "¬\U000f0c9a", b"\xb7\xb7")
def test_md5_file_b64_three_files(data1, text, data2):
    write_file("a.bin", "wb", data1)
    write_file("b.txt", "w", text, encoding="utf-8")
    write_file("c.bin", "wb", data2)
    data = data1 + read_file("b.txt", "rb") + data2
    # Intentionally provide the paths out of order (check sorting).
    path_hash = hashutil.md5_file_b64("c.bin", "a.bin", "b.txt")
    b64hash = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
    assert b64hash == path_hash


@given(st.binary(), st.text(), st.binary())
@settings(max_examples=10)
@example(b"g", "", b"\xb6DZ")
@example(b"\x1b\xb7", "¬\U000f0c9a", b"\xb7\xb7")
def test_md5_file_hex_three_files(data1, text, data2):
    write_file("a.bin", "wb", data1)
    write_file("b.txt", "w", text, encoding="utf-8")
    write_file("c.bin", "wb", data2)
    data = data1 + read_file("b.txt", "rb") + data2
    # Intentionally provide the paths out of order (check sorting).
    path_hash = hashutil.md5_file_hex("c.bin", "a.bin", "b.txt")
    assert hashlib.md5(data).hexdigest() == path_hash
