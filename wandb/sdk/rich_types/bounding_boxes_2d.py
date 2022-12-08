import pathlib
import codecs
import json
from .media import Media
from .type_checker import enforce_types

from typing import Optional, Dict, Union, List, Any, Sequence


@enforce_types
def validate_bounding_box(
    position: Dict[str, Any],
    class_id: Optional[int] = None,
    scores: Optional[Dict[str, Union[int, float]]] = None,
    box_caption: Optional[str] = None,
    domain: Optional[str] = None,
) -> None:
    @enforce_types
    def bound_position(
        minX: Union[int, float],
        maxX: Union[int, float],
        minY: Union[int, float],
        maxY: Union[int, float],
    ) -> None:
        ...

    @enforce_types
    def center_position(
        middle: List[Union[int, float]],
        width: Union[int, float],
        height: Union[int, float],
    ) -> None:
        ...

    try:
        bound_position(**position)
    except TypeError:
        try:
            center_position(**position)
            if len(position["middle"]) != 2:
                raise TypeError("middle must be a list of length 2")
        except TypeError:
            raise TypeError(
                "Position must be a dictionary with keys 'minX', 'maxX', 'minY', 'maxY' or 'middle', 'width', 'height'"
            )


class BoundingBoxes2D(Media):
    OBJ_TYPE = "boxes2D"
    RELATIVE_PATH = pathlib.Path("media") / "metadata" / OBJ_TYPE
    DEFAULT_FORMAT = "JSON"

    _format: str
    _source_path: pathlib.Path
    _is_temp_path: bool
    _bind_path: Optional[pathlib.Path]
    _size: int
    _sha256: str

    _name: str
    _classes: dict

    def __init__(self, bounding_box: dict, name: str) -> None:
        """Initialize a new wandb BoundingBox object."""

        self._name = name

        self._boxes = []
        self.add_boxes(bounding_box["box_data"])

        self._classes = dict()
        if "class_labels" in bounding_box:
            self.add_classes(bounding_box["class_labels"])

    def bind_to_run(
        self, interface, start: pathlib.Path, *prefix, name: Optional[str] = None
    ) -> None:
        """Bind this bounding box to a run.

        Args:
            interface: The interface to the run.
            start: The path to the run directory.
            prefix: A list of path components to prefix to the bounding box path.
            name: The name of the bounding box.
        """

        super().bind_to_run(
            interface,
            start,
            *prefix,
            name or self._sha256[:20],
            suffix=f".{self._format}",
        )

    def to_json(self) -> dict:
        return {
            "_type": self.OBJ_TYPE,
            "sha256": self._sha256,
            "size": self._size,
            "path": str(self._bind_path),
        }

    def _initialize(self, data: dict) -> None:
        """Initialize this bounding box.

        Args:
            data (dict): The data to initialize this bounding box with.
        """
        self._format = f".{self.OBJ_TYPE}.{self.DEFAULT_FORMAT}"
        self._source_path = self._generate_temp_path(suffix=self._format)
        self._is_temp_path = True
        with codecs.open(str(self._source_path), "w", encoding="utf-8") as f:
            json.dump(data, f)

        self._sha256 = self._compute_sha256(self._source_path)
        self._size = self._source_path.stat().st_size

    def add_classes(self, classes: Sequence[dict]) -> None:
        """Add classes to this bounding box.

        Args:
            classes (list): The classes to add.
        """
        for class_label in classes:
            class_id = class_label["id"]
            class_name = class_label["name"]
            self._classes[class_id] = class_name

    def add_boxes(self, boxes: list) -> None:
        """Add boxes to this bounding box.

        Args:
            boxes (list): The boxes to add.
        """
        for box in boxes:
            try:
                validate_bounding_box(**box)
                self._boxes.append(box)
            except TypeError as e:
                raise ValueError("Invalid bounding box data", e)
