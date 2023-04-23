import base64
import binascii
import hashlib

import pytest
from hypothesis import composite, given
from hypothesis import strategies as st
from wandb.sdk.lib import hashutil
from wandb.sdk.lib.hashutil import B64_MD5 as B64MD5
from wandb.sdk.lib.hashutil import Digest, MD5Digest, RefDigest
from wandb.sdk.lib.hashutil import E_Tag as ETag
from wandb.sdk.lib.hashutil import Hex_MD5 as HexMD5


def test_md5_string():
    assert hashutil.md5_string("") == "1B2M2Y8AsgTpgAmY7PhCfg=="
    assert hashutil.md5_string("foo") == "rL0Y20zC+Fzt72VPzMSk2A=="


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
    open("binfile", "wb").write(data)
    assert hashlib.md5(data).hexdigest() == hashutil.md5_file_hex("binfile")


@given(st.binary(), st.text(), st.binary())
def test_md5_file_b64_three_files(data1, text, data2):
    open("a.bin", "wb").write(data1)
    open("b.txt", "w", encoding="utf-8").write(text)
    open("c.bin", "wb").write(data2)
    data = data1 + open("b.txt", "rb").read() + data2
    # Intentionally provide the paths out of order (check sorting).
    path_hash = hashutil.md5_file_b64("c.bin", "a.bin", "b.txt")
    b64hash = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
    assert b64hash == path_hash


@given(st.binary(), st.text(), st.binary())
def test_md5_file_hex_three_files(data1, text, data2):
    open("a.bin", "wb").write(data1)
    open("b.txt", "w", encoding="utf-8").write(text)
    open("c.bin", "wb").write(data2)
    data = data1 + open("b.txt", "rb").read() + data2
    # Intentionally provide the paths out of order (check sorting).
    path_hash = hashutil.md5_file_hex("c.bin", "a.bin", "b.txt")
    assert hashlib.md5(data).hexdigest() == path_hash


digests = st.binary(min_size=8, max_size=64)


@composite
def hexadecimal(draw, data=digests):
    return draw(data).hex()


@composite
def b64encoded(draw, data=digests):
    return base64.b64encode(draw(data)).decode("ascii")


def test_b64md5_string():
    assert B64MD5.hash_string("") == "1B2M2Y8AsgTpgAmY7PhCfg=="
    assert B64MD5.hash_string("foo") == "rL0Y20zC+Fzt72VPzMSk2A=="


@given(st.binary(min_size=16))
def test_hex_to_b64_id_(data):
    hex_str = data.hex()
    assert B64MD5(HexMD5(hex_str)) == base64.b64encode(data).decode("ascii")


@given(st.binary(min_size=16))
def test_b64_to_hex_id_(data):
    b64str = base64.b64encode(data).decode("ascii")
    assert HexMD5(B64MD5(b64str)) == data.hex()


@given(st.binary())
def test_b64_to_hex_id_bytes_(data):
    b64 = base64.b64encode(data)
    assert HexMD5(B64MD5.from_bytes(b64)) == data.hex()


@given(hexadecimal)
def test_hexmd5_on_bytes(data):
    assert bytes(HexMD5(data)) == data


@given(b64encoded)
def test_b64md5_on_bytes(data):
    assert bytes(B64MD5(data)) == data


def test_invalid_hexmd5():
    for undecodable in (
        "0" * 25,  # Wrong parity (== 1 mod 4).
        "=B2M2Y8AsgTpgAmY7PhCfg==",  # '=' in non-padding position.
        "rL0Y20zC+Fzt72VPzMSk2A",  # Missing padding.
        "rL0Y20zC+Fzt72VPzMSk2^==",  # Character outside alphabet.
    ):
        with pytest.raises(ValueError, match="Invalid hex encoded MD5 digest"):
            HexMD5(undecodable)
        etag = ETag(undecodable)  # Can construct!
        with pytest.raises(ValueError, match="Invalid hex encoded MD5 digest"):
            bytes(etag)

    for wrong_length in (
        "f" * 12,  # Too short (8 bytes).
        "0" * 48,  # Too long (32 bytes).
    ):
        with pytest.raises(ValueError, match="Invalid hex encoded MD5 digest"):
            HexMD5(wrong_length)


def test_invalid_b64md5():
    for undecodable in (
        "0" * 25,  # Wrong parity (== 1 mod 4).
        "=B2M2Y8AsgTpgAmY7PhCfg==",  # '=' in non-padding position.
        "rL0Y20zC+Fzt72VPzMSk2A",  # Missing padding.
        "rL0Y20zC+Fzt72VPzMSk2^==",  # Character outside alphabet.
    ):
        with pytest.raises(ValueError, match="Invalid hex encoded MD5 digest"):
            B64MD5(undecodable)
        etag = ETag(undecodable)  # Can construct!
        with pytest.raises(ValueError, match="Invalid hex encoded MD5 digest"):
            bytes(etag)

    for wrong_length in (
        "f" * 12,  # Too short (8 bytes).
        "0" * 48,  # Too long (32 bytes).
    ):
        with pytest.raises(ValueError, match="Invalid hex encoded MD5 digest"):
            B64MD5(wrong_length)


def test_md5_file_b64_no_files_():
    b64hash = base64.b64encode(hashlib.md5(b"").digest()).decode("ascii")
    assert b64hash == B64MD5.hash_files()


@given(st.binary())
def test_md5_file_hex_single_file_(data):
    open("binfile", "wb").write(data)
    assert hashlib.md5(data).hexdigest() == HexMD5.hash_files("binfile")


@given(st.binary(), st.text(), st.binary())
def test_md5_file_b64_three_files_(data1, text, data2):
    open("a.bin", "wb").write(data1)
    open("b.txt", "w", encoding="utf-8").write(text)
    open("c.bin", "wb").write(data2)
    data = data1 + open("b.txt", "rb").read() + data2
    # Intentionally provide the paths out of order (check sorting).
    path_hash = B64MD5.hash_files("c.bin", "a.bin", "b.txt")
    b64hash = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
    assert b64hash == path_hash


@given(st.binary(), st.text(), st.binary())
def test_md5_file_hex_three_files_(data1, text, data2):
    open("a.bin", "wb").write(data1)
    open("b.txt", "w", encoding="utf-8").write(text)
    open("c.bin", "wb").write(data2)
    data = data1 + open("b.txt", "rb").read() + data2
    # Intentionally provide the paths out of order (check sorting).
    path_hash = HexMD5.hash_files("c.bin", "a.bin", "b.txt")
    assert hashlib.md5(data).hexdigest() == path_hash


@given(st.binary())
def test_hex_md5(data):
    assert HexMD5.hash_bytes(data) == hashlib.md5(data).hexdigest()


@given(st.binary())
def test_b64_md5(data):
    b64_md5 = B64MD5.hash_bytes(data)
    reference_digest = hashlib.md5(data).digest()
    assert b64_md5 == base64.standard_b64encode(reference_digest).decode("ascii")


@given(st.text(min_size=24, max_size=128))
def test_etag_legal_bytes(data):
    etag = ETag(data)
    try:
        # If we return a value, it should be valid.
        etag_bytes = bytes(etag)
        assert (
            (etag_bytes == bytes.fromhex(data))
            or (etag_bytes == base64.standard_b64decode(data))
            or (etag_bytes == base64.urlsafe_b64decode(data))
        )
    except (ValueError, binascii.Error):
        # ETags aren't actually restricted to these values.
        pass


@given(st.binary())
def test_etag_on_standard_b64(data):
    encoded = base64.standard_b64encode(data).decode("ascii")
    etag = ETag(encoded)
    assert bytes(etag) == data


@given(st.binary())
def test_etag_on_urlsafe_b64(data):
    encoded = base64.urlsafe_b64encode(data).decode("ascii")
    etag = ETag(encoded)
    assert bytes(etag) == data


def test_cant_instantiate_abstracts():
    with pytest.raises(NotImplementedError):
        Digest()
    with pytest.raises(NotImplementedError):
        MD5Digest()


def test_type_hierarchy():
    b = bytes(B64MD5.hash_string(""))
    b64 = B64MD5.from_bytes(b)
    md5 = MD5Digest.from_bytes(b)
    etag = ETag(b64)
    ref = RefDigest(etag)

    # Subtypes match
    for digest in (b64, md5, etag, ref):
        assert isinstance(digest, str)
        assert isinstance(digest, Digest)
    assert isinstance(b64, MD5Digest)
    assert isinstance(md5, MD5Digest)

    # Others do not
    assert not isinstance(etag, MD5Digest)
    assert not isinstance(ref, MD5Digest)
    assert not isinstance(b64, ETag)
    assert not isinstance(md5, ETag)
    assert not isinstance(ref, ETag)
    assert not isinstance(b64, RefDigest)
    assert not isinstance(md5, RefDigest)
    assert not isinstance(etag, RefDigest)
