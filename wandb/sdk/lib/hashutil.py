import base64
import hashlib
import mmap
import os
import sys
from pathlib import Path
from typing import Any, NewType, Union

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

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


class Digest(str):
    def __new__(cls, digest: Union[str, bytes, "Digest"]) -> Self:
        if isinstance(digest, Digest):
            return cls.from_bytes(bytes(digest))
        if isinstance(digest, bytes):
            return cls.from_bytes(digest)
        return super().__new__(cls, digest)

    def __init__(self, *_: Any) -> None:
        """Ensure the input is a valid digest."""
        raise NotImplementedError

    def __bytes__(self) -> bytes:
        """Convert to the byte representation if there is one."""
        raise NotImplementedError

    @classmethod
    def from_bytes(cls, bytes_: bytes) -> Self:
        """Convert from the byte representation if there is one."""
        raise NotImplementedError


class MD5Digest(Digest):
    """Abstract class with methods common to MD5 digests."""

    @classmethod
    def hash_bytes(cls, bytes_: bytes) -> Self:
        return cls.from_bytes(_md5(bytes_).digest())

    @classmethod
    def hash_string(cls, string: str) -> Self:
        return cls.hash_bytes(string.encode("utf-8"))

    @classmethod
    def hash_files(cls, *paths: StrPath) -> Self:
        return cls.from_bytes(_md5_file_hasher(*paths).digest())


class B64_MD5(MD5Digest):  # noqa: N801
    """Base64 encoded MD5 digest."""

    def __init__(self, *_: Any) -> None:
        try:
            assert len(bytes(self)) == 16
        except (AssertionError, ValueError) as e:
            raise ValueError(f"Invalid base-64 encoded MD5 digest: {self!r}") from e

    def __bytes__(self) -> bytes:
        return base64.standard_b64decode(self)

    @classmethod
    def from_bytes(cls, bytes_: bytes) -> Self:
        return super().__new__(cls, base64.standard_b64encode(bytes_).decode("ascii"))


class Hex_MD5(MD5Digest):  # noqa: N801
    """Hex encoded MD5 digest."""

    def __init__(self, *_: Any) -> None:
        try:
            assert len(bytes(self)) == 16
        except (AssertionError, ValueError) as e:
            raise ValueError(f"Invalid hex encoded MD5 digest: {self!r}") from e

    def __bytes__(self) -> bytes:
        return bytes.fromhex(self)

    @classmethod
    def from_bytes(cls, bytes_: bytes) -> Self:
        return super().__new__(cls, bytes_.hex())


class E_Tag(Digest):  # noqa: N801
    """Entity Tag for an object in remote storage.

    ETags are often but not always MD5 digests. Sometimes they are hex encoded,
    sometimes base64 encoded; in general they are simply opaque values that change when
    an object's contents change, so we can't validate them in any way.
    """

    def __new__(cls, digest: Union[str, bytes, Digest]) -> Self:
        if isinstance(digest, bytes):
            raise ValueError(f"Unable to construct ETag from byte value: {digest!r}")
        # Don't change the representation of a Digest.
        return super().__new__(cls, str(digest))

    def __init__(self, *_: Any) -> None:
        # A base-64 encoded MD5 is 24 characters long and a hex encoded SHA-512 can be
        # up to 128 characters; lengths outside this range are unreasonable and probably
        # a programming error (e.g. using the contents of the file instead of the ETag).
        if len(self) < 24 or len(self) > 128:
            raise ValueError(f"Etags must be between 16 and 64 bytes: {self!r}")

    def __bytes__(self) -> bytes:
        """Convert the ETag to the bytes it represents.

        In theory we can't differentiate between hex and base64 encodings of arbitrary
        length, but the chance of ambiguity in practice is less than 1 in 16 million
        even before counting length considerations. We don't attempt to decode other
        encodings since we don't know what they might be.
        """
        # Try to hex decode it first, since that's basically guaranteed to fail if it
        # isn't specifically a hex encoding.
        # Assumption: no sane hex encoding uses mixed case, so we can discard those.
        skip_hex = self.lower() != self and self.upper() != self
        try:
            if not skip_hex:
                return bytes.fromhex(self)
        except ValueError:
            pass

        # Otherwise, try base64 decoding it.
        try:
            return base64.standard_b64decode(self)
        except ValueError:
            # Just because we can't do it doesn't mean it's invalid; but this operation
            # won't succeed so we have to raise an exception.
            raise ValueError(f"Unable to decode ETag: {self!r}")

    @classmethod
    def from_bytes(cls, bytes_: bytes) -> Self:
        raise ValueError(f"Unable to construct ETag from byte value: {bytes_!r}")


class RefDigest(Digest):
    """Reference "digests" are URIs we use when we can't get the actual digest."""

    def __new__(cls, digest: Union[str, Digest]) -> Self:
        return super().__new__(cls, str(digest))

    def __init__(self, *_: Any) -> None:
        pass
