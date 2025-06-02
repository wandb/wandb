import re
from typing import Any, Dict, Final, Optional

from wandb.sdk.artifacts.artifact import Artifact

PLACEHOLDER: Final[str] = "PLACEHOLDER"


def sanitize_artifact_name(name: str) -> str:
    """Sanitize the string to satisfy constraints on artifact names."""
    from wandb.sdk.lib.hashutil import _md5

    # If the name is already sanitized, don't change it.
    if (sanitized := re.sub(r"[^a-zA-Z0-9_\-.]+", "", name)) == name:
        return name

    # Append an alphanumeric suffix to maintain uniqueness of the name.
    suffix = _md5(name.encode("utf-8")).hexdigest()
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
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        incremental: bool = False,
        use_as: Optional[str] = None,
    ) -> None:
        sanitized_name = sanitize_artifact_name(name)
        super().__init__(
            sanitized_name, PLACEHOLDER, description, metadata, incremental, use_as
        )
        self._type = type
