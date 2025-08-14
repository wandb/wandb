from __future__ import annotations

import re
from base64 import urlsafe_b64encode
from typing import Any, Final
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
    """InternalArtifact is used to create artifacts that are intended for internal use.

    This includes artifacts of type: `job`, `code`(with `source-` prefix in the collection name),
    `run_table` (with `run-` prefix in the collection name), and artifacts that start with `wandb-`.
    Users should not use this class directly.
    """

    def __init__(
        self,
        name: str,
        type: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        incremental: bool = False,
        use_as: str | None = None,
    ) -> None:
        sanitized_name = sanitize_artifact_name(name)
        super().__init__(
            sanitized_name, PLACEHOLDER, description, metadata, incremental, use_as
        )
        self._type = type
