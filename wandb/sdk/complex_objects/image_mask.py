import pathlib
from typing import Union, Optional, TYPE_CHECKING, Sequence

from .media import Media
import PIL.Image

if TYPE_CHECKING:
    import numpy as np


class ImageMask(Media):
    """Format image masks or overlays for logging to W&B."""

    OBJ_TYPE = "mask"
    RELATIVE_PATH = pathlib.Path("media") / "images" / OBJ_TYPE
    DEFAULT_FORMAT = "PNG"

    _source_path: pathlib.Path
    _is_temp_path: bool
    _bind_path: Optional[pathlib.Path]

    _size: int
    _sha256: str
    _format: str

    _name: str
    _classes: dict

    def __init__(self, mask: dict, name: str) -> None:
        """Initialize a new wandb ImageMask object."""
        data_or_path = mask.get("mask_data") or mask.get("path")

        if isinstance(data_or_path, (str, pathlib.Path)):
            self.from_path(data_or_path)
        elif isinstance(data_or_path, np.ndarray):
            self.from_numpy(data_or_path)
        else:
            raise ValueError("ImageMask must be initialized with a path, numpy array")

        self._name = name

        self._classes = dict()
        if "class_labels" in mask:
            self.add_classes(mask["class_labels"])

    def to_json(self) -> dict:
        return {
            "_type": self.OBJ_TYPE,
            "size": self._size,
            "sha256": self._sha256,
            "path": str(self._bind_path),
        }

    def bind_to_run(
        self, interface, start: pathlib.Path, *prefix, name: Optional[str] = None
    ) -> None:
        """Bind this mask to a run.

        Args:
            interface: The interface to the run.
            start: The path to the run directory.
            prefix: A list of path components to prefix to the mask path.
            name: The name of the mask object.
        """

        super().bind_to_run(
            interface,
            start,
            *prefix,
            name or self._sha256[:20],
            suffix=f".{self._format}",
        )

    def add_classes(self, classes: Sequence[dict]) -> None:
        """Add classes to this mask.

        Args:
            classes (Sequence): A list of class labels.
        """
        for class_label in classes:
            class_id = class_label["id"]
            class_name = class_label["name"]
            self._classes[class_id] = class_name

    def from_path(self, path: Union[pathlib.Path, str]) -> None:
        """Create an ImageMask from a path.

        Args:
            path (pathlib.Path): The path to the mask.
        """

        path = pathlib.Path(path).absolute()
        if not path.exists():
            raise ValueError(f"ImageMask path {path} does not exist")
        self._source_path = path
        self._format = self._source_path.suffix[1:]
        self._is_temp_path = False
        self._size = self._source_path.stat().st_size
        self._sha256 = self._compute_sha256(self._source_path)

    def from_numpy(self, array: "np.ndarray", mode: str = "L") -> None:
        """Create an ImageMask from an array.

        Args:
            array (np.ndarray): The array to use as the mask.
        """

        array = array.astype(np.int8)
        image = PIL.Image.fromarray(array, mode=mode)
        self._format = f"{self.OBJ_TYPE}.{self.DEFAULT_FORMAT}".lower()
        self._source_path = self._generate_temp_path(f".{self._format}")
        self._is_temp_path = True
        image.save(
            self._source_path,
            format=self.DEFAULT_FORMAT,
            transparency=None,
        )
        self._size = self._source_path.stat().st_size
        self._sha256 = self._compute_sha256(self._source_path)
