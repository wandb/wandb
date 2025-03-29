import codecs
import itertools
import json
import os
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Literal,
    Optional,
    Sequence,
    Set,
    TextIO,
    Tuple,
    Type,
    TypedDict,
    Union,
)

import wandb
from wandb import util
from wandb.sdk.lib import runid
from wandb.sdk.lib.paths import LogicalPath

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.media import BatchableMedia

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np
    import numpy.typing as npt

    from wandb.sdk.artifacts.artifact import Artifact

    from ..wandb_run import Run as LocalRun

    numeric = Union[int, float, np.integer, np.float64]
    FileFormat3D = Literal[
        "obj",
        "gltf",
        "glb",
        "babylon",
        "stl",
        "pts.json",
    ]
    Point3D = Tuple[numeric, numeric, numeric]
    Point3DWithCategory = Tuple[numeric, numeric, numeric, numeric]
    Point3DWithColors = Tuple[numeric, numeric, numeric, numeric, numeric, numeric]
    Point = Union[Point3D, Point3DWithCategory, Point3DWithColors]
    PointCloudType = Literal["lidar/beta"]
    RGBColor = Tuple[numeric, numeric, numeric]

    Quaternion = Tuple[numeric, numeric, numeric, numeric]

    class Box3D(TypedDict):
        corners: Tuple[
            Point3D,
            Point3D,
            Point3D,
            Point3D,
            Point3D,
            Point3D,
            Point3D,
            Point3D,
        ]
        label: Optional[str]
        color: RGBColor
        score: Optional[numeric]

    class Vector3D(TypedDict):
        start: Sequence[Point3D]
        end: Sequence[Point3D]

    class Camera(TypedDict):
        viewpoint: Sequence[Point3D]
        target: Sequence[Point3D]


def _install_numpy_error() -> "wandb.Error":
    return wandb.Error(
        "wandb.Object3D requires NumPy. To get it, run 'pip install numpy'."
    )


def _normalize_vec(x: "np.ndarray") -> "np.ndarray":
    """Normalizes a non-zero 1-dimensional array."""
    try:
        import numpy as np
    except ImportError as e:
        raise _install_numpy_error() from e

    x = abs(x)
    argmax = x.argmax()

    if x[argmax] == 0:
        raise ValueError("Unexpected zero quaternion.")

    # Rescale by the largest component first to be more numerically
    # stable than dividing by the norm directly.
    x = x / x[argmax]
    return x / np.linalg.norm(x)


def _quaternion_to_rotation(quaternion: "np.ndarray") -> "np.ndarray":
    """Returns the rotation matrix corresponding to a non-zero quaternion.

    The corresponding rotation matrix transforms column vectors by
    post-multiplication: `x @ R`. This way, it can be used to
    transform an Nx3 NumPy array of points as `points @ R`.
    """
    try:
        import numpy as np
    except ImportError as e:
        raise _install_numpy_error() from e

    # Precompute a few products to simplify the expression below.
    qr, qi, qj, qk = _normalize_vec(quaternion)
    qii, qjj, qkk = qi**2, qj**2, qk**2
    qij, qik, qjk = qi * qj, qi * qk, qj * qk
    qir, qjr, qkr = qi * qr, qj * qr, qk * qr

    return np.array(
        (
            (1 - 2 * (qjj + qkk), 2 * (qij + qkr), 2 * (qik - qjr)),
            (2 * (qij - qkr), 1 - 2 * (qii + qkk), 2 * (qjk + qir)),
            (2 * (qik + qjr), 2 * (qjk - qir), 1 - 2 * (qii + qjj)),
        ),
        dtype=np.float64,
    )


def box3d(
    *,
    center: "npt.ArrayLike",
    size: "npt.ArrayLike",
    orientation: "npt.ArrayLike",
    color: "RGBColor",
    label: "Optional[str]" = None,
    score: "Optional[numeric]" = None,
) -> "Box3D":
    """Returns a Box3D.

    Args:
        center: The center point of the box as a length-3 ndarray.
        size: The box's X, Y and Z dimensions as a length-3 ndarray.
        orientation: The rotation transforming global XYZ coordinates
            into the box's local XYZ coordinates, given as a length-4
            ndarray [r, x, y, z] corresponding to the non-zero quaternion
            r + xi + yj + zk.
        color: The box's color as an (r, g, b) tuple with 0 <= r,g,b <= 1.
        label: An optional label for the box.
        score: An optional score for the box.
    """
    try:
        import numpy as np
    except ImportError as e:
        raise _install_numpy_error() from e

    center = np.asarray(center, dtype=np.float64)
    size = np.asarray(size, dtype=np.float64)
    orientation = np.asarray(orientation, dtype=np.float64)

    assert center.shape == (3,)
    assert size.shape == (3,)
    assert orientation.shape == (4,)

    # Precompute the rotation matrix.
    rot = _quaternion_to_rotation(orientation)

    # Scale, rotate and translate each corner of the unit box.
    unit_corners = np.array(
        list(itertools.product((-1, 1), (-1, 1), (-1, 1))),
        dtype=np.float64,
    )
    corners = center + (0.5 * size * unit_corners) @ rot

    return {
        # Ignore the type because mypy can't infer that the list has length 8:
        # https://github.com/python/mypy/issues/7509
        "corners": tuple(tuple(pt) for pt in corners),  # type: ignore
        "color": color,
        "label": label,
        "score": score,
    }


class Object3D(BatchableMedia):
    """Wandb class for 3D point clouds.

    Args:
        data_or_path: (numpy array, string, io)
            Object3D can be initialized from a file or a numpy array.

            You can pass a path to a file or an io object and a file_type
            which must be one of SUPPORTED_TYPES

    The shape of the numpy array must be one of either:
    ```
    [[x y z],       ...] nx3
    [[x y z c],     ...] nx4 where c is a category with supported range [1, 14]
    [[x y z r g b], ...] nx6 where is rgb is color
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
    SUPPORTED_POINT_CLOUD_TYPES: ClassVar[Set[str]] = {"lidar/beta"}
    _log_type: ClassVar[str] = "object3D-file"

    def __init__(
        self,
        data_or_path: Union["np.ndarray", str, "TextIO", dict],
        caption: Optional[str] = None,
        **kwargs: Optional[Union[str, "FileFormat3D"]],
    ) -> None:
        super().__init__(caption=caption)

        if hasattr(data_or_path, "name"):
            # if the file has a path, we just detect the type and copy it from there
            data_or_path = data_or_path.name

        if hasattr(data_or_path, "read"):
            if hasattr(data_or_path, "seek"):
                data_or_path.seek(0)
            object_3d = data_or_path.read()

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

            extension = "." + extension

            tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + extension)
            with open(tmp_path, "w") as f:
                f.write(object_3d)

            self._set_file(tmp_path, is_tmp=True, extension=extension)
        elif isinstance(data_or_path, str):
            path = data_or_path
            extension = None
            for supported_type in Object3D.SUPPORTED_TYPES:
                if path.endswith(supported_type):
                    extension = "." + supported_type
                    break

            if not extension:
                raise ValueError(
                    "File '"
                    + path
                    + "' is not compatible with Object3D: supported types are: "
                    + ", ".join(Object3D.SUPPORTED_TYPES)
                )

            self._set_file(data_or_path, is_tmp=False, extension=extension)
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

            tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + ".pts.json")
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
                    """
                    The shape of the numpy array must be one of either
                                    [[x y z],       ...] nx3
                                     [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
                                     [x y z r g b], ...] nx6 where rgb is color
                    """
                )

            list_data = np_data.tolist()
            tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + ".pts.json")
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
    def from_file(
        cls,
        data_or_path: Union["TextIO", str],
        file_type: Optional["FileFormat3D"] = None,
    ) -> "Object3D":
        """Initializes Object3D from a file or stream.

        Args:
            data_or_path (Union["TextIO", str]): A path to a file or a `TextIO` stream.
            file_type (str): Specifies the data format passed to `data_or_path`. Required when `data_or_path` is a
                `TextIO` stream. This parameter is ignored if a file path is provided. The type is taken from the file extension.
        """
        # if file_type is not None and file_type not in cls.SUPPORTED_TYPES:
        #     raise ValueError(
        #         f"Unsupported file type: {file_type}. Supported types are: {cls.SUPPORTED_TYPES}"
        #     )
        return cls(data_or_path, file_type=file_type)

    @classmethod
    def from_numpy(cls, data: "np.ndarray") -> "Object3D":
        """Initializes Object3D from a numpy array.

        Args:
            data (numpy array): Each entry in the array will
                represent one point in the point cloud.


        The shape of the numpy array must be one of either:
        ```
        [[x y z],       ...]  # nx3.
        [[x y z c],     ...]  # nx4 where c is a category with supported range [1, 14].
        [[x y z r g b], ...]  # nx6 where is rgb is color.
        ```
        """
        if not util.is_numpy_array(data):
            raise ValueError("`data` must be a numpy array")

        if len(data.shape) != 2 or data.shape[1] not in {3, 4, 6}:
            raise ValueError(
                """
                The shape of the numpy array must be one of either:
                                [[x y z],       ...] nx3
                                 [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
                                 [x y z r g b], ...] nx6 where rgb is color
                """
            )

        return cls(data)

    @classmethod
    def from_point_cloud(
        cls,
        points: Sequence["Point"],
        boxes: Sequence["Box3D"],
        vectors: Optional[Sequence["Vector3D"]] = None,
        point_cloud_type: "PointCloudType" = "lidar/beta",
        # camera: Optional[Camera] = None,
    ) -> "Object3D":
        """Initializes Object3D from a python object.

        Args:
            points (Sequence["Point"]): The points in the point cloud.
            boxes (Sequence["Box3D"]): 3D bounding boxes for labeling the point cloud. Boxes
            are displayed in point cloud visualizations.
            vectors (Optional[Sequence["Vector3D"]]): Each vector is displayed in the point cloud
                visualization. Can be used to indicate directionality of bounding boxes. Defaults to None.
            point_cloud_type ("lidar/beta"): At this time, only the "lidar/beta" type is supported. Defaults to "lidar/beta".
        """
        if point_cloud_type not in cls.SUPPORTED_POINT_CLOUD_TYPES:
            raise ValueError("Point cloud type not supported")

        numpy = wandb.util.get_module(
            "numpy",
            required="wandb.Object3D.from_point_cloud requires numpy. Install with `pip install numpy`",
        )

        data = {
            "type": point_cloud_type,
            "points": numpy.array(points),
            "boxes": numpy.array(boxes),
            "vectors": numpy.array(vectors) if vectors is not None else numpy.array([]),
        }

        return cls(data)

    @classmethod
    def get_media_subdir(cls: Type["Object3D"]) -> str:
        return os.path.join("media", "object3D")

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = Object3D._log_type

        if isinstance(run_or_artifact, wandb.Artifact):
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
            expected = LogicalPath(cls.get_media_subdir())
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
