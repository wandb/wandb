from __future__ import annotations

import re
from base64 import urlsafe_b64encode
from typing import Any, Final, Literal
from zlib import crc32

from wandb.sdk.artifacts.artifact import Artifact

PLACEHOLDER: Final[str] = "PLACEHOLDER"


def sanitize_artifact_name(name: str) -> str:
    """Sanitize the string to satisfy constraints on artifact names."""
    # If the name is already sanitized, don't change it.
    if (sanitized := re.sub(r"[^a-zA-Z0-9_\-.]+", "", name)) == name:
        return name

    # Append a short alphanumeric suffix to maintain uniqueness.
    # Yes, CRC is meant for checksums and not as a general hash function, but
    # a 32-bit CRC hash, encoded as (url-safe) base64, is fairly short while
    # providing 4B+ possible values, which should be good enough for the corner
    # case names this function is meant to address.
    #
    # As implemented, the final suffix should be 6 characters.
    crc: int = crc32(name.encode("utf-8")) & 0xFFFFFFFF  # Ensure it's unsigned
    crc_bytes = crc.to_bytes(4, byteorder="big")
    suffix = urlsafe_b64encode(crc_bytes).rstrip(b"=").decode("ascii")

    return f"{sanitized}-{suffix}"


class InternalArtifact(Artifact):
    """An Artifact intended for internal use only.

    Includes artifacts of type `job`, `code` (with a `source-` collection name
    prefix), `run_table` (with a `run-` collection name prefix), and any type that starts
    with `wandb-`. Users should not use this class directly.
    """

    def __init__(
        self,
        name: str,
        type: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        incremental: bool = False,
        use_as: str | None = None,
        digest_algorithm: Literal["MD5", "XXH128"] = "MD5",
    ) -> None:
        sanitized_name = sanitize_artifact_name(name)

        if type == "job":
            # Match go-core JobBuilder / ArtifactBuilder, which always uses MD5.
            digest_algorithm = "MD5"

        super().__init__(
            sanitized_name,
            PLACEHOLDER,
            description,
            metadata,
            incremental,
            use_as,
            digest_algorithm=digest_algorithm,
        )
        self._type = type
