import json
import pathlib
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, TextIO, Union

import numpy as np

from .media import Media, MediaSequence, register

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run


class Object3D(Media):
    RELATIVE_PATH = pathlib.Path("media") / "object3D"
    OBJ_TYPE = "object3D-file"
    OBJ_ARTIFACT_TYPE = "object3D-file"

    DEFAULT_FORMAT = "PTS.JSON"

    SUPPORTED_TYPES = {"obj", "babylon", "stl", "glb", "gltf", "stl", "pts.json"}
    SUPPORTED_POINT_CLOUD_TYPES = {"lidar/beta"}

    def __init__(self, data_or_path, **kwargs: Any) -> None:
        super().__init__()
        if isinstance(data_or_path, (str, pathlib.Path)):
            self.from_path(data_or_path)
        elif isinstance(data_or_path, np.ndarray):
            self.from_numpy(data_or_path)
        elif isinstance(data_or_path, TextIO):
            self.from_buffer(data_or_path, **kwargs)
        elif isinstance(data_or_path, dict):
            self.from_point_cloud(**data_or_path, **kwargs)
        else:
            raise ValueError(
                "Object3D must be initialized with a path, numpy array, or file-like object"
            )

    def from_buffer(self, buffer: "TextIO", format: str) -> None:
        self._format = format.lower()
        assert self._format in self.SUPPORTED_TYPES, f"Unsupported format: {format}"

        with self.manager.save(suffix=f".{self._format}") as source_path:
            with open(source_path, "w") as f:
                if hasattr(buffer, "seek"):
                    buffer.seek(0)
                f.write(buffer.read())

    def from_path(self, path: Union[str, pathlib.Path]) -> None:
        with self.manager.save(path) as source_path:
            self._format = (source_path.suffix[1:] or self.DEFAULT_FORMAT).lower()
            assert (
                self._format in self.SUPPORTED_TYPES
            ), f"Unsupported format: {self._format}"

    def from_numpy(self, array: np.ndarray) -> None:
        assert array.ndim == 2 and array.shape[1] in {3, 4, 6}
        data = array.tolist()
        self._from_data(data)

    def from_point_cloud(
        self, points, boxes, vectors=None, point_cloud_type="lidar/beta"
    ) -> None:
        assert (
            point_cloud_type in self.SUPPORTED_POINT_CLOUD_TYPES
        ), f"Unsupported point cloud type: {point_cloud_type}"

        points = np.array(points).tolist() if points is not None else []
        boxes = np.array(boxes).tolist() if boxes is not None else []
        vectors = np.array(vectors).tolist() if vectors is not None else []

        data = {
            "points": points,
            "boxes": boxes,
            "vectors": vectors,
            "type": point_cloud_type,
        }
        self._from_data(data)

    def _from_data(self, data: Union[Dict[str, List], List]) -> None:
        self._format = self.DEFAULT_FORMAT.lower()
        with self.manager.save(suffix=f".{self._format}") as source_path:
            with open(source_path, "w", encoding="utf-8") as f:
                json.dump(
                    data,
                    f,
                    separators=(",", ":"),
                    sort_keys=True,
                    indent=4,
                )

    def bind_to_run(
        self, run: "Run", *namespace: str, name: Optional[str] = None
    ) -> None:
        """Binds the object to a run.

        Args:
            run (Run): The run to bind to.
            namespace (str): The namespace to bind to.
            name (str): The name to bind to.
        """
        super().bind_to_run(
            run,
            *namespace,
            name=name,
            suffix=f".{self._format}",
        )


@register(Object3D)
class Object3DSequence(MediaSequence[Any, Object3D]):
    OBJ_TYPE = "object3D"
    OBJ_ARTIFACT_TYPE = "object3D"

    def __init__(
        self,
        data: Sequence[Object3D],
    ) -> None:
        super().__init__(data, Object3D)

    def to_json(self) -> dict:
        items = [item.to_json() for item in self._items]
        return {
            "_type": self.OBJ_TYPE,
            "count": len(items),
            "objects": items,
            "filenames": [pathlib.Path(item["path"]).name for item in items],
        }
