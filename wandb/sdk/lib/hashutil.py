from __future__ import annotations

import hashlib
import mmap
import sys
from base64 import standard_b64decode, standard_b64encode
from functools import partial
from typing import TYPE_CHECKING, Callable, Iterable, NewType

from wandb.sdk.lib.paths import StrPath

if TYPE_CHECKING:
    import _hashlib  # type: ignore[import-not-found]

ETag = NewType("ETag", str)
HexMD5 = NewType("HexMD5", str)
B64MD5 = NewType("B64MD5", str)


_md5: Callable[..., _hashlib.HASH]
"""Allow FIPS-compliant md5 hash when supported."""
# Note: It's faster to check the Python version here,
# instead of at runtime before each call to md5.
if sys.version_info >= (3, 9):
    _md5 = partial(hashlib.md5, usedforsecurity=False)
else:
    _md5 = hashlib.md5


def md5_string(s: str) -> B64MD5:
    hasher = _md5(s.encode("utf-8"))
    return _b64_from_hasher(hasher)


def _b64_from_hasher(hasher: _hashlib.HASH) -> B64MD5:
    b64str = standard_b64encode(hasher.digest()).decode("ascii")
    return B64MD5(b64str)


def b64_to_hex_id(b64str: str) -> HexMD5:
    hexstr = standard_b64decode(b64str).hex()
    return HexMD5(hexstr)


def hex_to_b64_id(hexstr: str | bytes) -> B64MD5:
    hexstr = hexstr.decode("utf-8") if isinstance(hexstr, bytes) else hexstr
    b64str = standard_b64encode(bytes.fromhex(hexstr)).decode("utf-8")
    return B64MD5(b64str)


def md5_file_b64(*paths: StrPath) -> B64MD5:
    hasher = _file_hasher(paths)
    return _b64_from_hasher(hasher)


def md5_file_hex(*paths: StrPath) -> HexMD5:
    hasher = _file_hasher(paths)
    return HexMD5(hasher.hexdigest())


_KB: int = 1_024
_CHUNKSIZE: int = 128 * _KB
"""Chunk size (in bytes) for iteratively reading from file, if needed."""


def _file_hasher(paths: Iterable[StrPath]) -> _hashlib.HASH:
    hasher = _md5()

    # Note: We use str paths (instead of pathlib.Path objs) for minor perf improvements.
    for path in sorted(map(str, paths)):
        with open(path, "rb") as f:
            try:
                with mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_READ) as mview:
                    hasher.update(mview)
            except OSError:
                # This occurs if the mmap-ed file is on a different/mounted filesystem,
                # so we'll fall back on a less performant implementation.
                while chunk := f.read(_CHUNKSIZE):
                    hasher.update(chunk)
            except ValueError:
                # This occurs when mmap-ing an empty file, which can be skipped.
                # See: https://github.com/python/cpython/blob/986a4e1b6fcae7fe7a1d0a26aea446107dd58dd2/Modules/mmapmodule.c#L1589
                pass

    return hasher
