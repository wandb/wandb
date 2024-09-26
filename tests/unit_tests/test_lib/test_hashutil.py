from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from _pytest.fixtures import SubRequest
from pyfakefs.fake_filesystem import FakeFilesystem
from wandb.sdk.lib import hashutil

BYTE_STRS: tuple[bytes] = (
    b"",
    b"\xb7\xb7",
    b"\x89\xf3\xa2\xe1\xda",
)

TEXT_STRS: tuple[str] = (
    "",
    "foo",
    "¬\U000f0c9a",
)


@pytest.fixture(params=[pytest.param(b, id=f"bin{i}") for i, b in enumerate(BYTE_STRS)])
def bin_data(request: SubRequest) -> bytes:
    """Binary data."""
    return request.param


@pytest.fixture(params=[pytest.param(s, id=f"txt{i}") for i, s in enumerate(TEXT_STRS)])
def txt_data(request: SubRequest) -> str:
    """Text data."""
    return request.param


@pytest.fixture(params=[pytest.param(b, id=f"bin{i}") for i, b in enumerate(BYTE_STRS)])
def bin_data2(request: SubRequest) -> bytes:
    """A second instance of binary data, if needed."""
    return request.param


# ------------------------------------------------------------------------------
def test_md5_string():
    assert hashutil.md5_string("") == "1B2M2Y8AsgTpgAmY7PhCfg=="
    assert hashutil.md5_string("foo") == "rL0Y20zC+Fzt72VPzMSk2A=="


def test_hex_to_b64_id(bin_data):
    hex_str = bin_data.hex()
    assert hashutil.hex_to_b64_id(hex_str) == base64.b64encode(bin_data).decode("ascii")


def test_hex_to_b64_id_bytes(bin_data):
    hex_bytes = bin_data.hex().encode("ascii")
    expected_b64_id = base64.b64encode(bin_data).decode("ascii")
    assert hashutil.hex_to_b64_id(hex_bytes) == expected_b64_id


def test_b64_to_hex_id(bin_data):
    b64str = base64.b64encode(bin_data).decode("ascii")
    assert hashutil.b64_to_hex_id(b64str) == bin_data.hex()


def test_b64_to_hex_id_bytes(bin_data):
    b64 = base64.b64encode(bin_data)
    assert hashutil.b64_to_hex_id(b64) == bin_data.hex()


def test_md5_file_b64_no_files():
    b64hash = base64.b64encode(hashlib.md5(b"").digest()).decode("ascii")
    assert b64hash == hashutil.md5_file_b64()


def test_md5_file_hex_single_file(bin_data):
    fpath = Path("binfile")
    fpath.write_bytes(bin_data)
    assert hashlib.md5(bin_data).hexdigest() == hashutil.md5_file_hex(fpath)


def test_md5_file_hashes_on_three_files(bin_data, txt_data, bin_data2):
    fpath_a = Path("a.bin")
    fpath_b = Path("b.txt")
    fpath_c = Path("c.bin")

    fpath_a.write_bytes(bin_data)
    fpath_b.write_text(txt_data, encoding="utf-8")
    fpath_c.write_bytes(bin_data2)

    data = bin_data + fpath_b.read_bytes() + bin_data2
    expected_b64_hash = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
    expected_hex_hash = hashlib.md5(data).hexdigest()

    # Intentionally provide the paths out of order (check sorting).
    assert expected_b64_hash == hashutil.md5_file_b64(fpath_c, fpath_a, fpath_b)
    assert expected_hex_hash == hashutil.md5_file_hex(fpath_c, fpath_a, fpath_b)


@pytest.mark.parametrize(
    "filesize",
    [
        pytest.param(1024, id="1kB"),
        pytest.param(1024 * 1024, id="1MB"),
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

    chunk = b"data"  # short repeated bytestring for testing
    content = chunk * (filesize // len(chunk))

    # Simultaneously write the file and calculate the expected hash in chunks to conserve memory
    expected_md5 = hashlib.md5()
    expected_md5.update(content)

    fs.create_file(fpath_large, contents=content)

    expected_b64_hash = base64.b64encode(expected_md5.digest()).decode("ascii")
    expected_hex_hash = expected_md5.hexdigest()

    assert expected_b64_hash == hashutil.md5_file_b64(fpath_large)
    assert expected_hex_hash == hashutil.md5_file_hex(fpath_large)
