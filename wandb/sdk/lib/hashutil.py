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

    def update(self, data: bytes | bytearray | memoryview, /) -> None: ...
    def digest(self) -> bytes: ...
    def hexdigest(self) -> str: ...


logger = logging.getLogger(__name__)

# In the future, consider relying on pydantic to validate these types via e.g.
# - Base64Str: https://docs.pydantic.dev/latest/api/types/#pydantic.types.Base64Str
# - a custom EncodedStr + Encoder impl: https://docs.pydantic.dev/latest/api/types/#pydantic.types.EncodedStr
#
ETag: TypeAlias = str

HexMD5: TypeAlias = str
HexXXH64: TypeAlias = str
B64MD5: TypeAlias = str
B64XXH64: TypeAlias = str

HexDigest: TypeAlias = HexMD5 | HexXXH64
B64Digest: TypeAlias = B64MD5 | B64XXH64


# --- Hasher constructors ---


def _md5(data: bytes = b"") -> Hasher:
    """Allow FIPS-compliant md5 hash when supported."""
    return hashlib.md5(data, usedforsecurity=False)


def _xxh64(data: bytes = b"") -> Hasher:
    """Create an xxHash64 hasher (hashlib-compliant interface)."""
    return xxhash.xxh64(data)


# --- Encoding helpers  ---


def _b64_from_hasher(hasher: Hasher) -> B64Digest:
    return B64Digest(base64.b64encode(hasher.digest()).decode("ascii"))


def b64_to_hex_id(string: B64Digest) -> HexDigest:
    return HexDigest(base64.standard_b64decode(string).hex())


def hex_to_b64_id(encoded_string: str | bytes) -> B64Digest:
    if isinstance(encoded_string, bytes):
        encoded_string = encoded_string.decode("utf-8")
    as_str = bytes.fromhex(encoded_string)
    return B64Digest(base64.standard_b64encode(as_str).decode("utf-8"))


# --- MD5 public API ---


def md5_string(string: str) -> B64MD5:
    return B64MD5(_b64_from_hasher(_md5(string.encode("utf-8"))))


def md5_file_b64(*paths: StrPath) -> B64MD5:
    start_time = time.monotonic()
    digest = _b64_from_hasher(_md5_file_hasher(*paths))
    hash_time_seconds = time.monotonic() - start_time
    if hash_time_seconds > 1.0:
        logger.debug(
            "Computed MD5 hash for file. paths=%s, hashTimeMs=%d",
            paths,
            int(hash_time_seconds * 1000),
        )
    return B64MD5(digest)


def md5_file_hex(*paths: StrPath) -> HexMD5:
    return HexMD5(_md5_file_hasher(*paths).hexdigest())


def _md5_file_hasher(*paths: StrPath) -> Hasher:
    return _file_hasher(_md5(), *paths)


# --- xxHash64 public API ---


def xxh64_string(string: str) -> B64XXH64:
    return B64XXH64(_b64_from_hasher(_xxh64(string.encode("utf-8"))))


def xxh64_file_b64(*paths: StrPath) -> B64XXH64:
    start_time = time.monotonic()
    digest = _b64_from_hasher(_xxh64_file_hasher(*paths))
    hash_time_seconds = time.monotonic() - start_time
    if hash_time_seconds > 1.0:
        logger.debug(
            "Computed XXH64 hash for file. paths=%s, hashTimeMs=%d",
            paths,
            int(hash_time_seconds * 1000),
        )
    return B64XXH64(digest)


def xxh64_file_hex(*paths: StrPath) -> HexXXH64:
    return HexXXH64(_xxh64_file_hasher(*paths).hexdigest())


def _xxh64_file_hasher(*paths: StrPath) -> Hasher:
    return _file_hasher(_xxh64(), *paths)


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
                chunk = f.read(_CHUNKSIZE)
                while chunk:
                    hasher.update(chunk)
                    chunk = f.read(_CHUNKSIZE)
            except ValueError:
                # Empty file — mmap raises ValueError, safe to skip.
                pass

    return hasher
