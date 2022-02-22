import numbers
from typing import Any, Dict, Optional, Tuple, Type, TYPE_CHECKING, Union

import wandb

from ._json_metadata import JSONMetadata

if TYPE_CHECKING:
    from wandb.sdk.wandb_artifacts import Artifact
    from wandb.sdk.wandb_run import Run
    from wandb.apis.public import Artifact as PublicArtifact


class BBox2D:
    def __init__(
        self,
        point: Tuple[float, float],
        width: float,
        height: float,
        domain: Optional[str] = None,
        box_caption: Optional[str] = None,
        scores: Optional[Dict[str, float]] = None,
        class_id: Optional[int] = None,
    ) -> None:

        if not (len(point) == 2 and all(isinstance(p, numbers.Number) for p in point)):
            raise TypeError("`point` must be a tuple of lenght 2 with numerical values")
        if not isinstance(width, numbers.Number):
            raise TypeError(
                f"`width` must have a numerical value instead got {type(width)}"
            )
        if not isinstance(height, numbers.Number):
            raise TypeError(
                f"`height` must have a numerical value instead got {type(height)}"
            )

        if domain is None:
            minX, minY = point
            self._box = dict(
                position={"minX": minX, "maxX": width, "minY": minY, "maxY": height,}
            )
        elif domain == "pixel":
            self._box = dict(
                position={"middle": point, "width": width, "height": height,},
                domain=domain,
            )

        if box_caption is not None:
            if not isinstance(box_caption, str):
                raise TypeError(
                    f"`box_caption` must be a string instead got {type(box_caption)}"
                )
            else:
                self._box["box_caption"] = box_caption

        if class_id is not None:
            if not isinstance(class_id, int):
                raise TypeError(
                    f"`class_id` must be a integer instead got {type(class_id)}"
                )
            else:
                self._box["class_id"] = class_id

        if scores is not None:
            if not isinstance(scores, dict):
                raise TypeError(
                    f"`scores` must be a dictionary, instead got {type(scores)}"
                )
            else:
                self._box["scores"] = scores

    @property
    def class_id(self) -> Optional[int]:
        return self._box.get("class_id", None)

    def to_json(self) -> Dict[str, Any]:
        return self._box

    @classmethod
    def from_json(cls: Type["BBox2D"], box_dict: Dict[str, Any]) -> Type["BBox2D"]:
        kwargs = dict()

        bbox_expected_keys = {"domain", "box_caption", "class_id", "scores", "position"}

        for key in bbox_expected_keys:
            kwargs[key] = box_dict.get(key, None)

        if set(box_dict.keys()) - bbox_expected_keys:
            raise KeyError(f"Got unexpect argument(s): {set(box_dict.keys())}")

        position = kwargs.pop("position", None)
        if position is None:
            raise KeyError("Missing required argument: `position`")

        if not isinstance(position, dict):
            raise TypeError(
                f"`position` must be a dictionary instead got {type(position)}"
            )

        position_expected_keys = {
            "height",
            "width",
            "middle",
            "minX",
            "minY",
            "maxX",
            "maxY",
        }
        unexpected_keys = set(position.keys()) - position_expected_keys
        if unexpected_keys:
            raise KeyError(
                f"Got unexpected argument(s) for `position`:  {unexpected_keys}"
            )

        kwargs["height"] = position.get("height", None) or position.get("maxY", None)
        kwargs["width"] = position.get("width", None) or position.get("maxX", None)
        point = (position.get("minX", None), position.get("minY", None))
        kwargs["point"] = position.get("middle", None) or point

        return cls(**kwargs)


class BBoxes2D(JSONMetadata):
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

        class_labels = {
            0: "person",
            1: "car",
            2: "road",
            3: "building"
        }

        img = wandb.Image(image, boxes={
            "predictions": {
                "box_data": [
                    {
                        # one box expressed in the default relative/fractional domain
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4
                        },
                        "class_id" : 1,
                        "box_caption": class_labels[1],
                        "scores" : {
                            "acc": 0.2,
                            "loss": 1.2
                        }
                    },
                    {
                        # another box expressed in the pixel domain
                        "position": {
                            "middle": [150, 20],
                            "width": 68,
                            "height": 112
                        },
                        "domain" : "pixel",
                        "class_id" : 3,
                        "box_caption": "a building",
                        "scores" : {
                            "acc": 0.5,
                            "loss": 0.7
                        }
                    },
                    # Log as many boxes an as needed
                ],
                "class_labels": class_labels
            }
        })

        wandb.log({"driving_scene": img})
        ```

        ### Log a bounding box overlay to a Table
        <!--yeadoc-test:bb2d-image-with-labels-->
        ```python

        import numpy as np
        import wandb

        wandb.init()
        image = np.random.randint(low=0, high=256, size=(200, 300, 3))

        class_labels = {
            0: "person",
            1: "car",
            2: "road",
            3: "building"
        }

        class_set = wandb.Classes([
            {"name" : "person", "id" : 0},
            {"name" : "car", "id" : 1},
            {"name" : "road", "id" : 2},
            {"name" : "building", "id" : 3}
        ])

        img = wandb.Image(image, boxes={
            "predictions": {
                "box_data": [
                    {
                        # one box expressed in the default relative/fractional domain
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4
                        },
                        "class_id" : 1,
                        "box_caption": class_labels[1],
                        "scores" : {
                            "acc": 0.2,
                            "loss": 1.2
                        }
                    },
                    {
                        # another box expressed in the pixel domain
                        "position": {
                            "middle": [150, 20],
                            "width": 68,
                            "height": 112
                        },
                        "domain" : "pixel",
                        "class_id" : 3,
                        "box_caption": "a building",
                        "scores" : {
                            "acc": 0.5,
                            "loss": 0.7
                        }
                    },
                    # Log as many boxes an as needed
                ],
                "class_labels": class_labels
            }
        }, classes=class_set)

        table = wandb.Table(columns=["image"])
        table.add_data(img)
        wandb.log({"driving_scene": table})
        ```
    """

    _log_type = "bounding-boxes"
    # TODO: when the change is made to have this produce a dict with a _type, define
    # it here as _log_type, associate it in to_json

    def __init__(self, val: dict, key: str) -> None:
        """
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
        """
        super().__init__(val)

        self._key = key

        boxes = val["box_data"]
        if not isinstance(boxes, list):
            raise TypeError(f"`box_data` must be a list, instead got {type(boxes)}")

        _boxes = [BBox2D.from_json(box_dict) for box_dict in boxes]

        class_labels = val.get("class_labels", None)
        if class_labels is None:
            classes = set([box.class_id for box in _boxes]) - {None}
            class_labels = {c: f"class_{c}" for c in classes}
        self._class_labels = class_labels

        self._val = [box.to_json() for box in _boxes]

    def bind_to_run(
        self,
        run: "Run",
        key: Union[int, str],
        step: Union[int, str],
        id_: Optional[Union[int, str]] = None,
    ) -> None:
        # bind_to_run key argument is the Image parent key
        # the self._key value is the mask's sub key
        super().bind_to_run(run, key, step, id_=id_)
        run._add_singleton(
            "bounding_box/class_labels",
            str(key) + "_wandb_delimeter_" + self._key,
            self._class_labels,
        )

    @classmethod
    def type_name(cls) -> str:
        return "boxes2D"

    def validate(self, val: dict) -> bool:

        class_labels = val.get("class_labels", {})
        if not isinstance(class_labels, dict):
            raise TypeError(
                f"`class_label` must be a dictionary, got {type(class_labels)} instead"
            )
        for k, v in class_labels.items():
            if not (isinstance(k, numbers.Number) and isinstance(v, str)):
                raise TypeError(
                    f"`class_labels` must be a dictionary from number to strings, got {type(k)} to {type(v)} instead"
                )

        return True

    def to_json(self, run_or_artifact: Union["Run", "Artifact"]) -> dict:

        if isinstance(run_or_artifact, wandb.sdk.wandb_run.Run):
            return super().to_json(run_or_artifact)
        elif isinstance(run_or_artifact, wandb.sdk.wandb_artifacts.Artifact):
            # TODO (tim): I would like to log out a proper dictionary representing this object, but don't
            # want to mess with the visualizations that are currently available in the UI. This really should output
            # an object with a _type key. Will need to push this change to the UI first to ensure backwards compat
            return self._val
        else:
            raise ValueError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

    @classmethod
    def from_json(
        cls: Type["BBoxes2D"], json_obj: dict, source_artifact: "PublicArtifact"
    ) -> "BBoxes2D":
        return cls({"box_data": json_obj}, "")


BoundingBoxes2D = BBoxes2D
