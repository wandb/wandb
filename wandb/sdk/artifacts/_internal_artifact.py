from typing import Any, Dict, Final, Optional

from wandb.sdk.artifacts.artifact import Artifact

PLACEHOLDER: Final[str] = "PLACEHOLDER"


class InternalArtifact(Artifact):
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
