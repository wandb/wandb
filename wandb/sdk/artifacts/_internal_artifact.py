from typing import Any, Dict, Final, Optional

from wandb.sdk.artifacts.artifact import Artifact

PLACEHOLDER: Final[str] = "PLACEHOLDER"


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
        super().__init__(name, PLACEHOLDER, description, metadata, incremental, use_as)
        self._type = type
