import numbers
import os
from typing import TYPE_CHECKING, Optional, Type, Union

import wandb
from wandb import util
from wandb.sdk.lib import runid

from .._private import MEDIA_TMP
from ..base_types.media import Media

if TYPE_CHECKING:  # pragma: no cover
    from wandb.sdk.artifacts.artifact import Artifact

    from ...wandb_run import Run as LocalRun


class ImageMask(Media):
    """Format image masks or overlays for logging to W&B.

    Args:
        val: (dictionary)
            One of these two keys to represent the image:
                mask_data : (2D numpy array) The mask containing an integer class label
                    for each pixel in the image
                path : (string) The path to a saved image file of the mask
            class_labels : (dictionary of integers to strings, optional) A mapping of the
                integer class labels in the mask to readable class names. These will default
                to class_0, class_1, class_2, etc.

        key: (string)
            The readable name or id for this mask type (e.g. predictions, ground_truth)

    Examples:
        ### Logging a single masked image

        ```python
        import numpy as np
        import wandb

        run = wandb.init()
        image = np.random.randint(low=0, high=256, size=(100, 100, 3), dtype=np.uint8)
        predicted_mask = np.empty((100, 100), dtype=np.uint8)
        ground_truth_mask = np.empty((100, 100), dtype=np.uint8)

        predicted_mask[:50, :50] = 0
        predicted_mask[50:, :50] = 1
        predicted_mask[:50, 50:] = 2
        predicted_mask[50:, 50:] = 3

        ground_truth_mask[:25, :25] = 0
        ground_truth_mask[25:, :25] = 1
        ground_truth_mask[:25, 25:] = 2
        ground_truth_mask[25:, 25:] = 3

        class_labels = {0: "person", 1: "tree", 2: "car", 3: "road"}

        masked_image = wandb.Image(
            image,
            masks={
                "predictions": {
                    "mask_data": predicted_mask,
                    "class_labels": class_labels,
                },
                "ground_truth": {
                    "mask_data": ground_truth_mask,
                    "class_labels": class_labels,
                },
            },
        )
        run.log({"img_with_masks": masked_image})
        ```

        ### Log a masked image inside a Table

        ```python
        import numpy as np
        import wandb

        run = wandb.init()
        image = np.random.randint(low=0, high=256, size=(100, 100, 3), dtype=np.uint8)
        predicted_mask = np.empty((100, 100), dtype=np.uint8)
        ground_truth_mask = np.empty((100, 100), dtype=np.uint8)

        predicted_mask[:50, :50] = 0
        predicted_mask[50:, :50] = 1
        predicted_mask[:50, 50:] = 2
        predicted_mask[50:, 50:] = 3

        ground_truth_mask[:25, :25] = 0
        ground_truth_mask[25:, :25] = 1
        ground_truth_mask[:25, 25:] = 2
        ground_truth_mask[25:, 25:] = 3

        class_labels = {0: "person", 1: "tree", 2: "car", 3: "road"}

        class_set = wandb.Classes(
            [
                {"name": "person", "id": 0},
                {"name": "tree", "id": 1},
                {"name": "car", "id": 2},
                {"name": "road", "id": 3},
            ]
        )

        masked_image = wandb.Image(
            image,
            masks={
                "predictions": {
                    "mask_data": predicted_mask,
                    "class_labels": class_labels,
                },
                "ground_truth": {
                    "mask_data": ground_truth_mask,
                    "class_labels": class_labels,
                },
            },
            classes=class_set,
        )

        table = wandb.Table(columns=["image"])
        table.add_data(masked_image)
        run.log({"random_field": table})
        ```
    """

    _log_type = "mask"

    def __init__(self, val: dict, key: str) -> None:
        """Initialize an ImageMask object.

        Args:
            val: (dictionary) One of these two keys to represent the image:
                mask_data : (2D numpy array) The mask containing an integer class label
                    for each pixel in the image
                path : (string) The path to a saved image file of the mask
                class_labels : (dictionary of integers to strings, optional) A mapping
                    of the integer class labels in the mask to readable class names.
                    These will default to class_0, class_1, class_2, etc.

        key: (string)
            The readable name or id for this mask type (e.g. predictions, ground_truth)
        """
        super().__init__()

        if "path" in val:
            self._set_file(val["path"])
        else:
            np = util.get_module("numpy", required="Image mask support requires numpy")
            # Add default class mapping
            if "class_labels" not in val:
                classes = np.unique(val["mask_data"]).astype(np.int32).tolist()
                class_labels = {c: "class_" + str(c) for c in classes}
                val["class_labels"] = class_labels

            self.validate(val)
            self._val = val
            self._key = key

            ext = "." + self.type_name() + ".png"
            tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + ext)

            pil_image = util.get_module(
                "PIL.Image",
                required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
            )
            image = pil_image.fromarray(val["mask_data"].astype(np.int8), mode="L")

            image.save(tmp_path, transparency=None)
            self._set_file(tmp_path, is_tmp=True, extension=ext)

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
        if hasattr(self, "_val") and "class_labels" in self._val:
            class_labels = self._val["class_labels"]

            run._add_singleton(
                "mask/class_labels",
                str(key) + "_wandb_delimeter_" + self._key,
                class_labels,
            )

    @classmethod
    def get_media_subdir(cls: Type["ImageMask"]) -> str:
        return os.path.join("media", "images", cls.type_name())

    @classmethod
    def from_json(
        cls: Type["ImageMask"], json_obj: dict, source_artifact: "Artifact"
    ) -> "ImageMask":
        return cls(
            {"path": source_artifact.get_entry(json_obj["path"]).download()},
            key="",
        )

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        from wandb.sdk.wandb_run import Run

        json_dict = super().to_json(run_or_artifact)

        if isinstance(run_or_artifact, Run):
            json_dict["_type"] = self.type_name()
            return json_dict
        elif isinstance(run_or_artifact, wandb.Artifact):
            # Nothing special to add (used to add "digest", but no longer used.)
            return json_dict
        else:
            raise ValueError("to_json accepts wandb_run.Run or wandb.Artifact")

    @classmethod
    def type_name(cls: Type["ImageMask"]) -> str:
        return cls._log_type

    def validate(self, val: dict) -> bool:
        np = util.get_module("numpy", required="Image mask support requires numpy")
        # 2D Make this work with all tensor(like) types
        if "mask_data" not in val:
            raise TypeError(
                'Missing key "mask_data": An image mask requires mask data: a 2D array representing the predictions'
            )
        else:
            error_str = "mask_data must be a 2D array"
            shape = val["mask_data"].shape
            if len(shape) != 2:
                raise TypeError(error_str)
            if not (
                (val["mask_data"] >= 0).all() and (val["mask_data"] <= 255).all()
            ) and issubclass(val["mask_data"].dtype.type, np.integer):
                raise TypeError("Mask data must be integers between 0 and 255")

        # Optional argument
        if "class_labels" in val:
            for k, v in list(val["class_labels"].items()):
                if (not isinstance(k, numbers.Number)) or (not isinstance(v, str)):
                    raise TypeError(
                        "Class labels must be a dictionary of numbers to strings"
                    )
        return True
