import codecs
import json
import os
from typing import ClassVar, Sequence, Set, Type, TYPE_CHECKING, Union

import wandb
from wandb import util

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.media import BatchableMedia

if TYPE_CHECKING:  # pragma: no cover
    from typing import TextIO

    import numpy as np  # type: ignore

    from ..wandb_artifacts import Artifact as LocalArtifact
    from ..wandb_run import Run as LocalRun


class Object3D(BatchableMedia):
    """
    Wandb class for 3D point clouds.

    Arguments:
        data_or_path: (numpy array, string, io)
            Object3D can be initialized from a file or a numpy array.

            You can pass a path to a file or an io object and a file_type
            which must be one of `"obj"`, `"gltf"`, `"glb"`, `"babylon"`, `"stl"`, `"pts.json"`.

    The shape of the numpy array must be one of either:
    ```python
    [[x y z],       ...] nx3
    [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
    [x y z r g b], ...] nx4 where is rgb is color
    ```
    """

    SUPPORTED_TYPES: ClassVar[Set[str]] = {
        "obj",
        "gltf",
        "glb",
        "babylon",
        "stl",
        "pts.json",
    }
    _log_type: ClassVar[str] = "object3D-file"

    def __init__(
        self, data_or_path: Union["np.ndarray", str, "TextIO"], **kwargs: str
    ) -> None:
        super().__init__()

        if hasattr(data_or_path, "name"):
            # if the file has a path, we just detect the type and copy it from there
            data_or_path = data_or_path.name  # type: ignore

        if hasattr(data_or_path, "read"):
            if hasattr(data_or_path, "seek"):
                data_or_path.seek(0)  # type: ignore
            object_3d = data_or_path.read()  # type: ignore

            extension = kwargs.pop("file_type", None)
            if extension is None:
                raise ValueError(
                    "Must pass file type keyword argument when using io objects."
                )
            if extension not in Object3D.SUPPORTED_TYPES:
                raise ValueError(
                    "Object 3D only supports numpy arrays or files of the type: "
                    + ", ".join(Object3D.SUPPORTED_TYPES)
                )

            tmp_path = os.path.join(
                MEDIA_TMP.name, util.generate_id() + "." + extension
            )
            with open(tmp_path, "w") as f:
                f.write(object_3d)

            self._set_file(tmp_path, is_tmp=True)
        elif isinstance(data_or_path, str):
            path = data_or_path
            extension = None
            for supported_type in Object3D.SUPPORTED_TYPES:
                if path.endswith(supported_type):
                    extension = supported_type
                    break

            if not extension:
                raise ValueError(
                    "File '"
                    + path
                    + "' is not compatible with Object3D: supported types are: "
                    + ", ".join(Object3D.SUPPORTED_TYPES)
                )

            self._set_file(data_or_path, is_tmp=False)
        # Supported different types and scene for 3D scenes
        elif isinstance(data_or_path, dict) and "type" in data_or_path:
            if data_or_path["type"] == "lidar/beta":
                data = {
                    "type": data_or_path["type"],
                    "vectors": data_or_path["vectors"].tolist()
                    if "vectors" in data_or_path
                    else [],
                    "points": data_or_path["points"].tolist()
                    if "points" in data_or_path
                    else [],
                    "boxes": data_or_path["boxes"].tolist()
                    if "boxes" in data_or_path
                    else [],
                }
            else:
                raise ValueError(
                    "Type not supported, only 'lidar/beta' is currently supported"
                )

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".pts.json")
            with codecs.open(tmp_path, "w", encoding="utf-8") as fp:
                json.dump(
                    data,
                    fp,
                    separators=(",", ":"),
                    sort_keys=True,
                    indent=4,
                )
            self._set_file(tmp_path, is_tmp=True, extension=".pts.json")
        elif util.is_numpy_array(data_or_path):
            np_data = data_or_path

            # The following assertion is required for numpy to trust that
            # np_data is numpy array. The reason it is behind a False
            # guard is to ensure that this line does not run at runtime,
            # which would cause a runtime error if the user's machine did
            # not have numpy installed.

            if TYPE_CHECKING:
                assert isinstance(np_data, np.ndarray)

            if len(np_data.shape) != 2 or np_data.shape[1] not in {3, 4, 6}:
                raise ValueError(
                    """The shape of the numpy array must be one of either
                                    [[x y z],       ...] nx3
                                     [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
                                     [x y z r g b], ...] nx4 where is rgb is color"""
                )

            list_data = np_data.tolist()
            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".pts.json")
            with codecs.open(tmp_path, "w", encoding="utf-8") as fp:
                json.dump(
                    list_data,
                    fp,
                    separators=(",", ":"),
                    sort_keys=True,
                    indent=4,
                )
            self._set_file(tmp_path, is_tmp=True, extension=".pts.json")
        else:
            raise ValueError("data must be a numpy array, dict or a file object")

    @classmethod
    def get_media_subdir(cls: Type["Object3D"]) -> str:
        return os.path.join("media", "object3D")

    def to_json(self, run_or_artifact: Union["LocalRun", "LocalArtifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = Object3D._log_type

        if isinstance(run_or_artifact, wandb.wandb_sdk.wandb_artifacts.Artifact):
            if self._path is None or not self._path.endswith(".pts.json"):
                raise ValueError(
                    "Non-point cloud 3D objects are not yet supported with Artifacts"
                )

        return json_dict

    @classmethod
    def seq_to_json(
        cls: Type["Object3D"],
        seq: Sequence["BatchableMedia"],
        run: "LocalRun",
        key: str,
        step: Union[int, str],
    ) -> dict:
        seq = list(seq)

        jsons = [obj.to_json(run) for obj in seq]

        for obj in jsons:
            expected = util.to_forward_slash_path(cls.get_media_subdir())
            if not obj["path"].startswith(expected):
                raise ValueError(
                    "Files in an array of Object3D's must be in the {} directory, not {}".format(
                        expected, obj["path"]
                    )
                )

        return {
            "_type": "object3D",
            "filenames": [
                os.path.relpath(j["path"], cls.get_media_subdir()) for j in jsons
            ],
            "count": len(jsons),
            "objects": jsons,
        }


class _Object3DFileType(_dtypes.Type):
    name = "object3D-file"
    types = [Object3D]


_dtypes.TypeRegistry.add(_Object3DFileType)
