import base64
import binascii
import hashlib
import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    import os


StrPath = Union[str, "os.PathLike[str]"]


class Digest(str, ABC):
    def __new__(cls, digest: Union[str, bytes, "Digest"]) -> "Digest":
        if isinstance(digest, "Digest"):
            return cls.from_bytes(bytes(digest))
        if isinstance(digest, bytes):
            return cls.from_bytes(digest)
        return super().__new__(cls, digest)

    @abstractmethod
    def __init__(self) -> None:
        """Ensure the input is a valid digest."""

    @abstractmethod
    def __bytes__(self) -> bytes:
        """Convert to the byte representation if there is one."""

    @abstractmethod
    def from_bytes(self, bytes_: bytes) -> "Digest":
        """Convert from the byte representation if there is one."""


class MD5Digest(Digest):
    """Abstract class with methods common to MD5 digests."""

    @classmethod
    def hash_bytes(cls, bytes_: bytes) -> "MD5Digest":
        return cls.from_bytes(_md5(bytes_).digest())

    @classmethod
    def hash_string(cls, string: str) -> "MD5Digest":
        return cls.hash_bytes(string.encode("utf-8"))

    @classmethod
    def hash_files(cls, *paths: StrPath) -> "MD5Digest":
        return cls.from_bytes(_md5_file_hasher(*paths).digest())


def _md5(data: bytes = b"") -> "hashlib._Hash":
    """Allow FIPS-compliant md5 hash when supported."""
    if sys.version_info >= (3, 9):
        return hashlib.md5(data, usedforsecurity=False)
    else:
        return hashlib.md5(data)


def _md5_file_hasher(*paths: StrPath) -> "hashlib._Hash":
    md5_hash = _md5()
    for path in sorted(str(p) for p in paths):
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                md5_hash.update(chunk)
    return md5_hash


class B64MD5(MD5Digest):
    """Base64 encoded MD5 digest."""

    def __init__(self) -> None:
        try:
            assert len(bytes(self)) == 16
        except (AssertionError, ValueError, binascii.Error) as e:
            raise ValueError(f"Invalid base-64 encoded MD5 digest: {self!r}") from e

    def __bytes__(self) -> bytes:
        return base64.standard_b64decode(self)

    def from_bytes(self, bytes_: bytes) -> Digest:
        return B64MD5(base64.standard_b64encode(bytes_).decode("ascii"))


class HexMD5(MD5Digest):
    """Hex encoded MD5 digest."""

    def __init__(self) -> None:
        try:
            assert len(bytes(self)) == 16
        except (AssertionError, ValueError) as e:
            raise ValueError(f"Invalid hex encoded MD5 digest: {self!r}") from e

    def __bytes__(self) -> bytes:
        return bytes.fromhex(self)

    def from_bytes(self, bytes_: bytes) -> Digest:
        return HexMD5(bytes_.hex())


class ETag(Digest):
    """Entity Tag for an object in remote storage.

    ETags are often but not always MD5 digests. Sometimes they are hex encoded,
    sometimes base64 encoded; in general they are simply opaque values that change when
    an object's contents change, so we can't validate them in any way.
    """

    def __new__(cls, digest: Union[str, bytes, "Digest"]) -> "Digest":
        if isinstance(digest, bytes):
            raise ValueError(f"Unable to construct ETag from byte value: {digest!r}")
        # Don't change the representation of a Digest.
        return super().__new__(cls, str(digest))

    def __init__(self) -> None:
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
        except (ValueError, binascii.Error):
            pass
        # Try an alternate base64 encoding.
        try:
            return base64.urlsafe_b64decode(self)
        except (ValueError, binascii.Error):
            raise ValueError(f"Unable to decode ETag: {self!r}")

    def from_bytes(self, bytes_: bytes) -> Digest:
        raise ValueError(f"Unable to construct ETag from byte value: {bytes_!r}")


class RefDigest(Digest):
    """Reference "digests" are URIs we use when we can't get the actual digest."""

    def __init__(self) -> None:
        pass
