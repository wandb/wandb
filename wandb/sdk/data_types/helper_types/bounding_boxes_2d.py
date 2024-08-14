import numbers
from typing import TYPE_CHECKING, Optional, Type, Union

import wandb
from wandb import util
from wandb.util import has_num

from ..base_types.json_metadata import JSONMetadata

if TYPE_CHECKING:  # pragma: no cover
    from wandb.sdk.artifacts.artifact import Artifact

    from ...wandb_run import Run as LocalRun


class BoundingBoxes2D(JSONMetadata):
    """Format images with 2D bounding box overlays for logging to W&B.

    Arguments:
        val: (dictionary) A dictionary of the following form:
            box_data: (list of dictionaries) One dictionary for each bounding box, containing:
                position: (dictionary) the position and size of the bounding box, in one of two formats
                    Note that boxes need not all use the same format.
                    {"minX", "minY", "maxX", "maxY"}: (dictionary) A set of coordinates defining
                        the upper and lower bounds of the box (the bottom left and top right corners)
                    {"middle", "width", "height"}: (dictionary) A set of coordinates defining the
                        center and dimensions of the box, with "middle" as a list [x, y] for the
                        center point and "width" and "height" as numbers
                domain: (string) One of two options for the bounding box coordinate domain
                    null: By default, or if no argument is passed, the coordinate domain
                        is assumed to be relative to the original image, expressing this box as a fraction
                        or percentage of the original image. This means all coordinates and dimensions
                        passed into the "position" argument are floating point numbers between 0 and 1.
                    "pixel": (string literal) The coordinate domain is set to the pixel space. This means all
                        coordinates and dimensions passed into "position" are integers within the bounds
                        of the image dimensions.
                class_id: (integer) The class label id for this box
                scores: (dictionary of string to number, optional) A mapping of named fields
                        to numerical values (float or int), can be used for filtering boxes in the UI
                        based on a range of values for the corresponding field
                box_caption: (string, optional) A string to be displayed as the label text above this
                        box in the UI, often composed of the class label, class name, and/or scores

            class_labels: (dictionary, optional) A map of integer class labels to their readable class names

        key: (string)
            The readable name or id for this set of bounding boxes (e.g. predictions, ground_truth)

    Examples:
        ### Log bounding boxes for a single image
        <!--yeadoc-test:boundingbox-2d-->
        ```python
        import numpy as np
        import wandb

        wandb.init()
        image = np.random.randint(low=0, high=256, size=(200, 300, 3))

        class_labels = {0: "person", 1: "car", 2: "road", 3: "building"}

        img = wandb.Image(
            image,
            boxes={
                "predictions": {
                    "box_data": [
                        {
                            # one box expressed in the default relative/fractional domain
                            "position": {"minX": 0.1, "maxX": 0.2, "minY": 0.3, "maxY": 0.4},
                            "class_id": 1,
                            "box_caption": class_labels[1],
                            "scores": {"acc": 0.2, "loss": 1.2},
                        },
                        {
                            # another box expressed in the pixel domain
                            "position": {"middle": [150, 20], "width": 68, "height": 112},
                            "domain": "pixel",
                            "class_id": 3,
                            "box_caption": "a building",
                            "scores": {"acc": 0.5, "loss": 0.7},
                        },
                        # Log as many boxes an as needed
                    ],
                    "class_labels": class_labels,
                }
            },
        )

        wandb.log({"driving_scene": img})
        ```

        ### Log a bounding box overlay to a Table
        <!--yeadoc-test:bb2d-image-with-labels-->
        ```python
        import numpy as np
        import wandb

        wandb.init()
        image = np.random.randint(low=0, high=256, size=(200, 300, 3))

        class_labels = {0: "person", 1: "car", 2: "road", 3: "building"}

        class_set = wandb.Classes(
            [
                {"name": "person", "id": 0},
                {"name": "car", "id": 1},
                {"name": "road", "id": 2},
                {"name": "building", "id": 3},
            ]
        )

        img = wandb.Image(
            image,
            boxes={
                "predictions": {
                    "box_data": [
                        {
                            # one box expressed in the default relative/fractional domain
                            "position": {"minX": 0.1, "maxX": 0.2, "minY": 0.3, "maxY": 0.4},
                            "class_id": 1,
                            "box_caption": class_labels[1],
                            "scores": {"acc": 0.2, "loss": 1.2},
                        },
                        {
                            # another box expressed in the pixel domain
                            "position": {"middle": [150, 20], "width": 68, "height": 112},
                            "domain": "pixel",
                            "class_id": 3,
                            "box_caption": "a building",
                            "scores": {"acc": 0.5, "loss": 0.7},
                        },
                        # Log as many boxes an as needed
                    ],
                    "class_labels": class_labels,
                }
            },
            classes=class_set,
        )

        table = wandb.Table(columns=["image"])
        table.add_data(img)
        wandb.log({"driving_scene": table})
        ```
    """

    _log_type = "bounding-boxes"
    # TODO: when the change is made to have this produce a dict with a _type, define
    # it here as _log_type, associate it in to_json

    def __init__(self, val: dict, key: str) -> None:
        """Initialize a BoundingBoxes object.

        The input dictionary `val` should contain the keys:
            box_data: a list of dictionaries, each of which describes a bounding box.
            class_labels: (optional) A map of integer class labels to their readable
                class names.

        Each bounding box dictionary should contain the following keys:
            position: (dictionary) the position and size of the bounding box.
            domain: (string) One of two options for the bounding box coordinate domain.
            class_id: (integer) The class label id for this box.
            scores: (dictionary of string to number, optional) A mapping of named fields
                to numerical values (float or int).
            box_caption: (optional) The label text, often composed of the class label,
                class name, and/or scores.

        The position dictionary should be in one of two formats:
            {"minX", "minY", "maxX", "maxY"}: (dictionary) A set of coordinates defining
                the upper and lower bounds of the box (the bottom left and top right
                corners).
            {"middle", "width", "height"}: (dictionary) A set of coordinates defining
                the center and dimensions of the box, with "middle" as a list [x, y] for
                the center point and "width" and "height" as numbers.
        Note that boxes need not all use the same format.

        Args:
            val: (dictionary) A dictionary containing the bounding box data.
            key: (string) The readable name or id for this set of bounding boxes (e.g.
                predictions, ground_truth)
        """
        super().__init__(val)
        self._val = val["box_data"]
        self._key = key
        # Add default class mapping
        if "class_labels" not in val:
            np = util.get_module(
                "numpy", required="Bounding box support requires numpy"
            )
            classes = (
                np.unique(list(box["class_id"] for box in val["box_data"]))
                .astype(np.int32)
                .tolist()
            )
            class_labels = {c: "class_" + str(c) for c in classes}
            self._class_labels = class_labels
        else:
            self._class_labels = val["class_labels"]

    def bind_to_run(
        self,
        run: "LocalRun",
        key: Union[int, str],
        step: Union[int, str],
        id_: Optional[Union[int, str]] = None,
        ignore_copy_err: Optional[bool] = None,
    ) -> None:
        # bind_to_run key argument is the Image parent key
        # the self._key value is the mask's sub key
        super().bind_to_run(run, key, step, id_=id_, ignore_copy_err=ignore_copy_err)
        run._add_singleton(
            "bounding_box/class_labels",
            str(key) + "_wandb_delimeter_" + self._key,
            self._class_labels,
        )

    @classmethod
    def type_name(cls) -> str:
        return "boxes2D"

    def validate(self, val: dict) -> bool:
        # Optional argument
        if "class_labels" in val:
            for k, v in list(val["class_labels"].items()):
                if (not isinstance(k, numbers.Number)) or (not isinstance(v, str)):
                    raise TypeError(
                        "Class labels must be a dictionary of numbers to string"
                    )

        boxes = val["box_data"]
        if not isinstance(boxes, list):
            raise TypeError("Boxes must be a list")

        for box in boxes:
            # Required arguments
            error_str = (
                "Each box must contain a position with: middle, width, and height or \
                    \nminX, maxX, minY, maxY."
            )
            if "position" not in box:
                raise TypeError(error_str)
            else:
                valid = False
                if (
                    "middle" in box["position"]
                    and len(box["position"]["middle"]) == 2
                    and has_num(box["position"], "width")
                    and has_num(box["position"], "height")
                ):
                    valid = True
                elif (
                    has_num(box["position"], "minX")
                    and has_num(box["position"], "maxX")
                    and has_num(box["position"], "minY")
                    and has_num(box["position"], "maxY")
                ):
                    valid = True

                if not valid:
                    raise TypeError(error_str)

            # Optional arguments
            if ("scores" in box) and not isinstance(box["scores"], dict):
                raise TypeError("Box scores must be a dictionary")
            elif "scores" in box:
                for k, v in list(box["scores"].items()):
                    if not isinstance(k, str):
                        raise TypeError("A score key must be a string")
                    if not isinstance(v, numbers.Number):
                        raise TypeError("A score value must be a number")

            if ("class_id" in box) and not isinstance(box["class_id"], int):
                raise TypeError("A box's class_id must be an integer")

            # Optional
            if ("box_caption" in box) and not isinstance(box["box_caption"], str):
                raise TypeError("A box's caption must be a string")
        return True

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        from wandb.sdk.wandb_run import Run

        if isinstance(run_or_artifact, Run):
            return super().to_json(run_or_artifact)
        elif isinstance(run_or_artifact, wandb.Artifact):
            # TODO (tim): I would like to log out a proper dictionary representing this object, but don't
            # want to mess with the visualizations that are currently available in the UI. This really should output
            # an object with a _type key. Will need to push this change to the UI first to ensure backwards compat
            return self._val
        else:
            raise ValueError("to_json accepts wandb_run.Run or wandb.Artifact")

    @classmethod
    def from_json(
        cls: Type["BoundingBoxes2D"], json_obj: dict, source_artifact: "Artifact"
    ) -> "BoundingBoxes2D":
        return cls({"box_data": json_obj}, "")
