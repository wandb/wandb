from __future__ import annotations

import base64
import hashlib
import mmap
import sys
from typing import TYPE_CHECKING, NewType

from wandb.sdk.lib.paths import StrPath

if TYPE_CHECKING:
    import _hashlib  # type: ignore[import-not-found]

ETag = NewType("ETag", str)
HexMD5 = NewType("HexMD5", str)
B64MD5 = NewType("B64MD5", str)


def _md5(data: bytes = b"") -> _hashlib.HASH:
    """Allow FIPS-compliant md5 hash when supported."""
    if sys.version_info >= (3, 9):
        return hashlib.md5(data, usedforsecurity=False)
    else:
        return hashlib.md5(data)


def md5_string(string: str) -> B64MD5:
    return _b64_from_hasher(_md5(string.encode("utf-8")))


def _b64_from_hasher(hasher: _hashlib.HASH) -> B64MD5:
    return B64MD5(base64.b64encode(hasher.digest()).decode("ascii"))


def b64_to_hex_id(string: B64MD5) -> HexMD5:
    return HexMD5(base64.standard_b64decode(string).hex())


def hex_to_b64_id(encoded_string: str | bytes) -> B64MD5:
    if isinstance(encoded_string, bytes):
        encoded_string = encoded_string.decode("utf-8")
    as_str = bytes.fromhex(encoded_string)
    return B64MD5(base64.standard_b64encode(as_str).decode("utf-8"))


def md5_file_b64(*paths: StrPath) -> B64MD5:
    return _b64_from_hasher(_md5_file_hasher(*paths))


def md5_file_hex(*paths: StrPath) -> HexMD5:
    return HexMD5(_md5_file_hasher(*paths).hexdigest())


_KB: int = 1_024
_CHUNKSIZE: int = 128 * _KB
"""Chunk size (in bytes) for iteratively reading from file, if needed."""


def _md5_file_hasher(*paths: StrPath) -> _hashlib.HASH:
    md5_hash = _md5()

    # Note: We use str paths (instead of pathlib.Path objs) for minor perf improvements.
    for path in sorted(map(str, paths)):
        with open(path, "rb") as f:
            try:
                with mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_READ) as mview:
                    md5_hash.update(mview)
            except OSError:
                # This occurs if the mmap-ed file is on a different/mounted filesystem,
                # so we'll fall back on a less performant implementation.

                # Note: At the time of implementation, the walrus operator `:=`
                # is avoided to maintain support for users on python 3.7.
                # Consider revisiting once 3.7 support is no longer needed.
                chunk = f.read(_CHUNKSIZE)
                while chunk:
                    md5_hash.update(chunk)
                    chunk = f.read(_CHUNKSIZE)
            except ValueError:
                # This occurs when mmap-ing an empty file, which can be skipped.
                # See: https://github.com/python/cpython/blob/986a4e1b6fcae7fe7a1d0a26aea446107dd58dd2/Modules/mmapmodule.c#L1589
                pass

    return md5_hash
