from __future__ import annotations

import base64
import hashlib
import logging
import mmap
import time
from typing import Protocol, TypeAlias

import xxhash

from wandb.sdk.lib.paths import StrPath


class Hasher(Protocol):
    """Protocol for hashlib-compatible hash objects."""

    def update(self, data: bytes | bytearray | mmap.mmap, /) -> None: ...
    def digest(self) -> bytes: ...
    def hexdigest(self) -> str: ...


logger = logging.getLogger(__name__)

# In the future, consider relying on pydantic to validate these types via e.g.
# - Base64Str: https://docs.pydantic.dev/latest/api/types/#pydantic.types.Base64Str
# - a custom EncodedStr + Encoder impl: https://docs.pydantic.dev/latest/api/types/#pydantic.types.EncodedStr
#
ETag: TypeAlias = str

HexDigest: TypeAlias = str
B64Digest: TypeAlias = str


# --- Hasher constructors ---


def _md5(data: bytes = b"") -> Hasher:
    """Allow FIPS-compliant md5 hash when supported."""
    return hashlib.md5(data, usedforsecurity=False)


def _xxh128(data: bytes = b"") -> Hasher:
    """Create an xxHash128 hasher (hashlib-compliant interface)."""
    return xxhash.xxh128(data)


# --- Encoding helpers  ---


def _b64_from_hasher(hasher: Hasher) -> B64Digest:
    return base64.b64encode(hasher.digest()).decode("ascii")


def b64_to_hex_id(string: B64Digest) -> HexDigest:
    return base64.standard_b64decode(string).hex()


def hex_to_b64_id(encoded_string: str | bytes) -> B64Digest:
    if isinstance(encoded_string, bytes):
        encoded_string = encoded_string.decode("utf-8")
    as_str = bytes.fromhex(encoded_string)
    return base64.standard_b64encode(as_str).decode("utf-8")


# --- MD5 public API ---


def md5_string(string: str) -> B64Digest:
    return _b64_from_hasher(_md5(string.encode("utf-8")))


def md5_file_b64(*paths: StrPath) -> B64Digest:
    start_time = time.monotonic()
    digest = _b64_from_hasher(_md5_file_hasher(*paths))
    if (secs := (time.monotonic() - start_time)) > 1.0:
        logger.debug(
            "Computed MD5 hash for file. paths=%s, hashTimeMs=%d",
            paths,
            int(secs * 1000),
        )
    return digest


def md5_file_hex(*paths: StrPath) -> HexDigest:
    return _md5_file_hasher(*paths).hexdigest()


def _md5_file_hasher(*paths: StrPath) -> Hasher:
    return _file_hasher(_md5(), *paths)


# --- xxHash128 public API ---


def xxh128_string(string: str) -> B64Digest:
    return _b64_from_hasher(_xxh128(string.encode("utf-8")))


def xxh128_file_b64(*paths: StrPath) -> B64Digest:
    start_time = time.monotonic()
    digest = _b64_from_hasher(_xxh128_file_hasher(*paths))
    if (secs := (time.monotonic() - start_time)) > 1.0:
        logger.debug(
            "Computed XXH128 hash for file. paths=%s, hashTimeMs=%d",
            paths,
            int(secs * 1000),
        )
    return digest


def xxh128_file_hex(*paths: StrPath) -> HexDigest:
    return _xxh128_file_hasher(*paths).hexdigest()


def _xxh128_file_hasher(*paths: StrPath) -> Hasher:
    return _file_hasher(_xxh128(), *paths)


# --- Shared file hashing implementation ---


_KB: int = 1_024
_CHUNKSIZE: int = 128 * _KB
"""Chunk size (in bytes) for iteratively reading from file, if needed."""


def _file_hasher(hasher: Hasher, *paths: StrPath) -> Hasher:
    for path in sorted(map(str, paths)):
        with open(path, "rb") as f:
            try:
                with mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_READ) as mview:
                    hasher.update(mview)
            except OSError:
                while chunk := f.read(_CHUNKSIZE):
                    hasher.update(chunk)
                    chunk = f.read(_CHUNKSIZE)
            except ValueError:
                # Empty file — mmap raises ValueError, safe to skip.
                pass

    return hasher
