import base64
import hashlib
from pathlib import Path
from typing import Optional

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pyfakefs.fake_filesystem import FakeFilesystem
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


@pytest.mark.parametrize(
    "filesize",
    [
        512,  # Smaller than chunking threshold
        2 * 1024 * 1024,  # Larger than chunking threshold
    ],
)
def test_md5_file_hashes_on_mounted_filesystem(filesize, tmp_path, fs: FakeFilesystem):
    # Some setup we have to do to get this test to play well with `pyfakefs`.
    # Note: Cast to str looks redundant but is intentional (for python<=3.10).
    # https://pytest-pyfakefs.readthedocs.io/en/latest/troubleshooting.html#pathlib-path-objects-created-outside-of-tests
    mount_dir = Path(str(tmp_path)) / "mount"

    # Simulate filepaths on the mounted filesystem
    fs.create_dir(mount_dir)
    fs.add_mount_point(str(mount_dir))

    fpath_large = mount_dir / "large.bin"

    content_chunk = b"data"  # short repeated bytestring for testing
    n_chunks = filesize // len(content_chunk)

    expected_md5 = hashlib.md5()
    with fpath_large.open("wb") as f:
        for _ in range(n_chunks):
            f.write(content_chunk)
            expected_md5.update(content_chunk)

    expected_b64_hash = base64.b64encode(expected_md5.digest()).decode("ascii")
    expected_hex_hash = expected_md5.hexdigest()

    assert expected_b64_hash == hashutil.md5_file_b64(fpath_large)
    assert expected_hex_hash == hashutil.md5_file_hex(fpath_large)
