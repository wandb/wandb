import base64
import hashlib
import mmap
import os
import sys
from pathlib import Path
from typing import NewType, Union

from wandb.sdk.lib.paths import StrPath

ETag = NewType("ETag", str)
HexMD5 = NewType("HexMD5", str)
B64MD5 = NewType("B64MD5", str)


def _md5(data: bytes = b"") -> "hashlib._Hash":
    """Allow FIPS-compliant md5 hash when supported."""
    if sys.version_info >= (3, 9):
        return hashlib.md5(data, usedforsecurity=False)
    else:
        return hashlib.md5(data)


def md5_string(string: str) -> B64MD5:
    return _b64_from_hasher(_md5(string.encode("utf-8")))


def _b64_from_hasher(hasher: "hashlib._Hash") -> B64MD5:
    return B64MD5(base64.b64encode(hasher.digest()).decode("ascii"))


def b64_to_hex_id(string: B64MD5) -> HexMD5:
    return HexMD5(base64.standard_b64decode(string).hex())


def hex_to_b64_id(encoded_string: Union[str, bytes]) -> B64MD5:
    if isinstance(encoded_string, bytes):
        encoded_string = encoded_string.decode("utf-8")
    as_str = bytes.fromhex(encoded_string)
    return B64MD5(base64.standard_b64encode(as_str).decode("utf-8"))


def md5_file_b64(*paths: StrPath) -> B64MD5:
    return _b64_from_hasher(_md5_file_hasher(*paths))


def md5_file_hex(*paths: StrPath) -> HexMD5:
    return HexMD5(_md5_file_hasher(*paths).hexdigest())


def _md5_file_hasher(*paths: StrPath) -> "hashlib._Hash":
    md5_hash = _md5()

    for path in sorted(Path(p) for p in paths):
        with path.open("rb") as f:
            if os.stat(f.fileno()).st_size <= 1024 * 1024:
                md5_hash.update(f.read())
            else:
                with mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_READ) as mview:
                    md5_hash.update(mview)

    return md5_hash
