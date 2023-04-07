import codecs
import json
import pathlib
from typing import Any, Optional, TextIO, Union

import numpy as np

from .media import Media


class Object3D(Media):
    OBJ_TYPE = "object3D-file"
    RELATIVE_PATH = pathlib.Path("media") / "object3D"
    SUPPORTED_FORMATS = ["obj", "babylon", "stl", "glb", "gltf", "stl", "pts.json"]
    DEFAULT_FORMAT = "PTS.JSON"

    SUPPORTED_POINT_CLOUD_TYPES = ["lidar/beta"]

    _format: str

    def __init__(self, data_or_path, **kwargs: Any) -> None:
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
        assert self._format in self.SUPPORTED_FORMATS

        with self.path.save(suffix=f".{self._format}") as path:
            with open(path, "w") as f:
                if hasattr(buffer, "seek"):
                    buffer.seek(0)
                f.write(buffer.read())

    def from_path(self, path: Union[str, pathlib.Path]) -> None:
        with self.path.save(path) as path:
            self._format = path.suffix[1:].lower()
            assert self._format in self.SUPPORTED_FORMATS

    def from_numpy(self, array: np.ndarray) -> None:
        assert array.ndim == 2 and array.shape[1] in {3, 4, 6}
        data = array.tolist()
        self._format = self.DEFAULT_FORMAT.lower()
        with self.path.save(suffix=f".{self._format}") as path:
            with codecs.open(str(path), "w", encoding="utf-8") as f:
                json.dump(
                    data,
                    f,
                    separators=(",", ":"),
                    sort_keys=True,
                    indent=4,
                )

    def from_point_cloud(
        self, points, boxes, vectors=None, point_cloud_type="lidar/beta"
    ) -> None:
        assert point_cloud_type in self.SUPPORTED_POINT_CLOUD_TYPES

        points = np.array(points).tolist() if points is not None else []
        boxes = np.array(boxes).tolist() if boxes is not None else []
        vectors = np.array(vectors).tolist() if vectors is not None else []

        data = {
            "points": points,
            "boxes": boxes,
            "vectors": vectors,
            "type": point_cloud_type,
        }

        self._format = self.DEFAULT_FORMAT.lower()
        with self.path.save(suffix=f".{self._format}") as path:
            with codecs.open(str(path), "w", encoding="utf-8") as f:
                json.dump(
                    data,
                    f,
                    separators=(",", ":"),
                    sort_keys=True,
                    indent=4,
                )

    def to_json(self) -> dict:
        serialized = super().to_json()
        serialized.update(
            {
                "_type": self.OBJ_TYPE,
            }
        )
        return serialized

    def bind_to_run(self, run, *namespace, name: Optional[str] = None) -> None:
        """Bind this 3d object to a run.

        Args:
            interface: The interface to the run.
            start: The path to the run directory.
            prefix: A list of path components to prefix to the 3d object path.
            name: The name of the 3d object.
        """
        super().bind_to_run(
            run,
            *namespace,
            name=name,
            suffix=f".{self._format}",
        )
