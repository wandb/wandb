import pathlib
from typing import TYPE_CHECKING, Optional, Sequence, Union

import PIL.Image

from .media import Media

if TYPE_CHECKING:
    import numpy as np


class ImageMask(Media):
    """Format image masks or overlays for logging to W&B."""

    OBJ_TYPE = "mask"
    RELATIVE_PATH = pathlib.Path("media") / "images" / OBJ_TYPE
    DEFAULT_FORMAT = "PNG"

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
            **super().to_json(),
        }

    def bind_to_run(self, run, *namespace, name: Optional[str] = None) -> None:
        """Bind this mask to a run.

        Args:
            run (wandb.sdk.wandb_run.Run): The run to bind to.
            *namespace: The namespace to bind to.
            name (str, optional): The name to bind to.
        """
        super().bind_to_run(
            run,
            *namespace,
            name=name,
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
        with self.manager.save(path) as path:
            if not path.exists():
                raise ValueError(f"ImageMask path {path} does not exist")
            self._format = path.suffix[1:]

    def from_numpy(self, array: "np.ndarray", mode: str = "L") -> None:
        """Create an ImageMask from an array.

        Args:
            array (np.ndarray): The array to use as the mask.
        """
        self._format = f"{self.OBJ_TYPE}.{self.DEFAULT_FORMAT}".lower()
        with self.manager.save(suffix=f".{self._format}") as path:
            array = array.astype(np.int8)
            image = PIL.Image.fromarray(array, mode=mode)
            image.save(path, format=self.DEFAULT_FORMAT, transparency=None)
