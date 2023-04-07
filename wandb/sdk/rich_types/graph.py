import pathlib
from typing import TYPE_CHECKING, Optional

from .media import Media

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run


class Graph(Media):
    OBJ_TYPE = "graph-file"
    OBJ_ARTIFACT_TYPE = "graph-file"
    RELATIVE_PATH = pathlib.Path("media") / "graph"
    DEFAULT_FORMAT = ".GRAPH.JSON"

    def __init__(self, data_or_path) -> None:
        super().__init__()
        self._format = self.DEFAULT_FORMAT.lower()

    def bind_to_run(
        self, run: "Run", *namespace: str, name: Optional[str] = None
    ) -> None:
        suffix = f".{self._format}"
        return super().bind_to_run(run, *namespace, name=name, suffix=suffix)

    # def to_json(self) -> Dict[str, Any]:
    #     return super().to_json()


class Node:
    def __init__(self, *_):
        ...


class Edge:
    def __init__(self, *_):
        ...
