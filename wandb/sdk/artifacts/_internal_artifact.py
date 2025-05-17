from typing import Any, Final

from .artifact import Artifact

PLACEHOLDER: Final[str] = "PLACEHOLDER"


class InternalArtifact(Artifact):
    def __init__(
        self,
        name: str,
        type: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        incremental: bool = False,
        use_as: str | None = None,
    ) -> None:
        super().__init__(name, PLACEHOLDER, description, metadata, incremental, use_as)
        self._type = type
