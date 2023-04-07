import pathlib
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

import numpy as np

from .media import Media

if TYPE_CHECKING:
    from wandb.sdk.wandb_artifacts import Artifact
    from wandb.sdk.wandb_run import Run


class Array(Media):
    OBJ_TYPE = "array-file"
    OBJ_ARTIFACT_TYPE = "array-file"
    RELATIVE_PATH = pathlib.Path("media") / "array"
    DEFAULT_FORMAT = "NPY"

    def __init__(self, data_or_path) -> None:
        super().__init__()
        if isinstance(data_or_path, (str, pathlib.Path)):
            self.from_path(data_or_path)
        else:
            self.from_array(data_or_path)

    def from_array(self, data) -> None:
        self._format = self.DEFAULT_FORMAT.lower()
        with self.path.save(suffix=f".{self._format}") as source_path:
            np.save(source_path, data)

    def from_path(self, path: Union[str, pathlib.Path]) -> None:
        with self.path.save(path) as source_path:
            self._format = (source_path.suffix[1:] or self.DEFAULT_FORMAT).lower()

    def bind_to_artifact(self, artifact: "Artifact") -> Dict[str, Any]:
        super().bind_to_artifact(artifact)
        return {
            "_type": self.OBJ_ARTIFACT_TYPE,
        }

    def bind_to_run(self, run: "Run", *namespace, name: Optional[str] = None) -> None:
        """Bind this audio object to a run.

        Args:
            run: The run to bind to.
            namespace: The namespace to use.
            name: The name of the audio object.
        """
        return super().bind_to_run(
            run,
            *namespace,
            name=name,
            suffix=f".{self._format}",
        )

    def to_json(self) -> Dict[str, Any]:
        return super().to_json()
