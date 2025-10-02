import hashlib
import logging
import os
import pathlib
from io import BytesIO
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Type, Union, cast
from urllib import parse

from packaging.version import parse as parse_version

import wandb
from wandb import util
from wandb.sdk.lib import hashutil, runid
from wandb.sdk.lib.paths import LogicalPath

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.media import BatchableMedia, Media
from .helper_types.bounding_boxes_2d import BoundingBoxes2D
from .helper_types.classes import Classes
from .helper_types.image_mask import ImageMask

if TYPE_CHECKING:  # pragma: no cover
    import matplotlib  # type: ignore
    import numpy as np
    import torch  # type: ignore
    from PIL.Image import Image as PILImage

    from wandb.sdk.artifacts.artifact import Artifact

    ImageDataType = Union[
        "matplotlib.artist.Artist", "PILImage", "TorchTensorType", "np.ndarray"
    ]
    ImageDataOrPathType = Union[str, pathlib.Path, "Image", ImageDataType]
    TorchTensorType = Union["torch.Tensor", "torch.Variable"]


def _warn_on_invalid_data_range(
    data: "np.ndarray",
    normalize: bool = True,
) -> None:
    if not normalize:
        return

    np = util.get_module(
        "numpy",
        required="wandb.Image requires numpy if not supplying PIL Images: pip install numpy",
    )

    if np.min(data) < 0 or np.max(data) > 255:
        wandb.termwarn(
            "Data passed to `wandb.Image` should consist of values in the range [0, 255], "
            "image data will be normalized to this range, "
            "but behavior will be removed in a future version of wandb.",
            repeat=False,
        )


def _guess_and_rescale_to_0_255(data: "np.ndarray") -> "np.ndarray":
    """Guess the image's format and rescale its values to the range [0, 255].

    This is an unfortunate design flaw carried forward for backward
    compatibility. A better design would have been to document the expected
    data format and not mangle the data provided by the user.

    If given data in the range [0, 1], we multiply all values by 255
    and round down to get integers.

    If given data in the range [-1, 1], we rescale it by mapping -1 to 0 and
    1 to 255, then round down to get integers.

    We clip and round all other data.
    """
    try:
        import numpy as np
    except ImportError:
        raise wandb.Error(
            "wandb.Image requires numpy if not supplying PIL images: pip install numpy"
        ) from None

    data_min: float = data.min()
    data_max: float = data.max()

    if 0 <= data_min and data_max <= 1:
        return (data * 255).astype(np.uint8)

    elif -1 <= data_min and data_max <= 1:
        return (255 * 0.5 * (data + 1)).astype(np.uint8)

    else:
        return data.clip(0, 255).astype(np.uint8)


def _convert_to_uint8(data: "np.ndarray") -> "np.ndarray":
    np = util.get_module(
        "numpy",
        required="wandb.Image requires numpy if not supplying PIL Images: pip install numpy",
    )
    return data.astype(np.uint8)


def _server_accepts_image_filenames(run: "wandb.Run") -> bool:
    if run.offline:
        return True

    # Newer versions of wandb accept large image filenames arrays
    # but older versions would have issues with this.
    max_cli_version = util._get_max_cli_version()
    if max_cli_version is None:
        return False

    accepts_image_filenames: bool = parse_version(max_cli_version) >= parse_version(
        "0.12.10"
    )
    return accepts_image_filenames


def _server_accepts_artifact_path(run: "wandb.Run") -> bool:
    if run.offline:
        return False

    max_cli_version = util._get_max_cli_version()
    if max_cli_version is None:
        return False

    return parse_version(max_cli_version) >= parse_version("0.12.14")


class Image(BatchableMedia):
    """A class for logging images to W&B."""

    MAX_ITEMS = 108

    # PIL limit
    MAX_DIMENSION = 65500

    _log_type = "image-file"

    format: Optional[str]
    _grouping: Optional[int]
    _caption: Optional[str]
    _width: Optional[int]
    _height: Optional[int]
    _image: Optional["PILImage"]
    _classes: Optional["Classes"]
    _boxes: Optional[Dict[str, "BoundingBoxes2D"]]
    _masks: Optional[Dict[str, "ImageMask"]]
    _file_type: Optional[str]

    def __init__(
        self,
        data_or_path: "ImageDataOrPathType",
        mode: Optional[str] = None,
        caption: Optional[str] = None,
        grouping: Optional[int] = None,
        classes: Optional[Union["Classes", Sequence[dict]]] = None,
        boxes: Optional[Union[Dict[str, "BoundingBoxes2D"], Dict[str, dict]]] = None,
        masks: Optional[Union[Dict[str, "ImageMask"], Dict[str, dict]]] = None,
        file_type: Optional[str] = None,
        normalize: bool = True,
    ) -> None:
        """Initialize a `wandb.Image` object.

        This class handles various image data formats and automatically normalizes
        pixel values to the range [0, 255] when needed, ensuring compatibility
        with the W&B backend.

        * Data in range [0, 1] is multiplied by 255 and converted to uint8
        * Data in range [-1, 1] is rescaled from [-1, 1] to [0, 255] by mapping
            -1 to 0 and 1 to 255, then converted to uint8
        * Data outside [-1, 1] but not in [0, 255] is clipped to [0, 255] and
            converted to uint8 (with a warning if values fall outside [0, 255])
        * Data already in [0, 255] is converted to uint8 without modification

        Args:
            data_or_path: Accepts NumPy array/pytorch tensor of image data,
                a PIL image object, or a path to an image file. If a NumPy
                array or pytorch tensor is provided,
                the image data will be saved to the given file type.
                If the values are not in the range [0, 255] or all values are in the range [0, 1],
                the image pixel values will be normalized to the range [0, 255]
                unless `normalize` is set to `False`.
            - pytorch tensor should be in the format (channel, height, width)
            - NumPy array should be in the format (height, width, channel)
            mode: The PIL mode for an image. Most common are "L", "RGB",
                "RGBA". Full explanation at https://pillow.readthedocs.io/en/stable/handbook/concepts.html#modes
            caption: Label for display of image.
            grouping: The grouping number for the image.
            classes: A list of class information for the image,
                used for labeling bounding boxes, and image masks.
            boxes: A dictionary containing bounding box information for the image.
                see https://docs.wandb.ai/ref/python/data-types/boundingboxes2d/
            masks: A dictionary containing mask information for the image.
                see https://docs.wandb.ai/ref/python/data-types/imagemask/
            file_type: The file type to save the image as.
                This parameter has no effect if `data_or_path` is a path to an image file.
            normalize: If `True`, normalize the image pixel values to fall within the range of [0, 255].
                Normalize is only applied if `data_or_path` is a numpy array or pytorch tensor.

        Examples:
        Create a wandb.Image from a numpy array

        ```python
        import numpy as np
        import wandb

        with wandb.init() as run:
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))
                image = wandb.Image(pixels, caption=f"random field {i}")
                examples.append(image)
            run.log({"examples": examples})
        ```

        Create a wandb.Image from a PILImage

        ```python
        import numpy as np
        from PIL import Image as PILImage
        import wandb

        with wandb.init() as run:
            examples = []
            for i in range(3):
                pixels = np.random.randint(
                    low=0, high=256, size=(100, 100, 3), dtype=np.uint8
                )
                pil_image = PILImage.fromarray(pixels, mode="RGB")
                image = wandb.Image(pil_image, caption=f"random field {i}")
                examples.append(image)
            run.log({"examples": examples})
        ```

        Log .jpg rather than .png (default)

        ```python
        import numpy as np
        import wandb

        with wandb.init() as run:
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))
                image = wandb.Image(
                    pixels, caption=f"random field {i}", file_type="jpg"
                )
                examples.append(image)
            run.log({"examples": examples})
        ```
        """
        super().__init__(caption=caption)
        # TODO: We should remove grouping, it's a terrible name and I don't
        # think anyone uses it.

        self._grouping = None
        self._width = None
        self._height = None
        self._image = None
        self._classes = None
        self._boxes = None
        self._masks = None
        self._file_type = None

        # Allows the user to pass an Image object as the first parameter and have a perfect copy,
        # only overriding additional metadata passed in. If this pattern is compelling, we can generalize.
        if isinstance(data_or_path, Image):
            self._initialize_from_wbimage(data_or_path)
        elif isinstance(data_or_path, (str, pathlib.Path)):
            data_or_path = str(data_or_path)

            if self.path_is_reference(data_or_path):
                self._initialize_from_reference(data_or_path)
            else:
                self._initialize_from_path(data_or_path)
        else:
            self._initialize_from_data(data_or_path, mode, file_type, normalize)
        self._set_initialization_meta(
            grouping, caption, classes, boxes, masks, file_type
        )

    def _set_initialization_meta(
        self,
        grouping: Optional[int] = None,
        caption: Optional[str] = None,
        classes: Optional[Union["Classes", Sequence[dict]]] = None,
        boxes: Optional[Union[Dict[str, "BoundingBoxes2D"], Dict[str, dict]]] = None,
        masks: Optional[Union[Dict[str, "ImageMask"], Dict[str, dict]]] = None,
        file_type: Optional[str] = None,
    ) -> None:
        if grouping is not None:
            self._grouping = grouping

        total_classes = {}

        if boxes:
            if not isinstance(boxes, dict):
                raise ValueError('Images "boxes" argument must be a dictionary')
            boxes_final: Dict[str, BoundingBoxes2D] = {}
            for key in boxes:
                box_item = boxes[key]
                if isinstance(box_item, BoundingBoxes2D):
                    boxes_final[key] = box_item
                elif isinstance(box_item, dict):
                    # TODO: Consider injecting top-level classes if user-provided is empty
                    boxes_final[key] = BoundingBoxes2D(box_item, key)
                total_classes.update(boxes_final[key]._class_labels)
            self._boxes = boxes_final

        if masks:
            if not isinstance(masks, dict):
                raise ValueError('Images "masks" argument must be a dictionary')
            masks_final: Dict[str, ImageMask] = {}
            for key in masks:
                mask_item = masks[key]
                if isinstance(mask_item, ImageMask):
                    masks_final[key] = mask_item
                elif isinstance(mask_item, dict):
                    # TODO: Consider injecting top-level classes if user-provided is empty
                    masks_final[key] = ImageMask(mask_item, key)
                if hasattr(masks_final[key], "_val"):
                    total_classes.update(masks_final[key]._val["class_labels"])
            self._masks = masks_final

        if classes is not None:
            if isinstance(classes, Classes):
                total_classes.update(
                    {val["id"]: val["name"] for val in classes._class_set}
                )
            else:
                total_classes.update({val["id"]: val["name"] for val in classes})

        if len(total_classes.keys()) > 0:
            self._classes = Classes(
                [
                    {"id": key, "name": total_classes[key]}
                    for key in total_classes.keys()
                ]
            )
        if self.image is not None:
            self._width, self._height = self.image.size
        self._free_ram()

    def _initialize_from_wbimage(self, wbimage: "Image") -> None:
        self._grouping = wbimage._grouping
        self._caption = wbimage._caption
        self._width = wbimage._width
        self._height = wbimage._height
        self._image = wbimage._image
        self._classes = wbimage._classes
        self._path = wbimage._path
        self._is_tmp = wbimage._is_tmp
        self._extension = wbimage._extension
        self._sha256 = wbimage._sha256
        self._size = wbimage._size
        self.format = wbimage.format
        self._file_type = wbimage._file_type
        self._artifact_source = wbimage._artifact_source
        self._artifact_target = wbimage._artifact_target

        # We do not want to implicitly copy boxes or masks, just the image-related data.
        # self._boxes = wbimage._boxes
        # self._masks = wbimage._masks

    def _initialize_from_path(self, path: str) -> None:
        pil_image = util.get_module(
            "PIL.Image",
            required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
        )
        self._set_file(path, is_tmp=False)
        self._image = pil_image.open(path)
        assert self._image is not None
        self._image.load()
        ext = os.path.splitext(path)[1][1:]
        self.format = ext

    def _initialize_from_reference(self, path: str) -> None:
        self._path = path
        self._is_tmp = False
        self._sha256 = hashlib.sha256(path.encode("utf-8")).hexdigest()
        path = parse.urlparse(path).path
        ext = path.split("/")[-1].split(".")[-1]
        self.format = ext

    def _initialize_from_data(
        self,
        data: "ImageDataType",
        mode: Optional[str] = None,
        file_type: Optional[str] = None,
        normalize: bool = True,
    ) -> None:
        pil_image = util.get_module(
            "PIL.Image",
            required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
        )

        accepted_formats = ["png", "jpg", "jpeg", "bmp"]
        self.format = file_type or "png"

        if self.format not in accepted_formats:
            raise ValueError(f"file_type must be one of {accepted_formats}")

        tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + "." + self.format)

        if util.is_matplotlib_typename(util.get_full_typename(data)):
            buf = BytesIO()
            util.ensure_matplotlib_figure(data).savefig(buf, format=self.format)
            self._image = pil_image.open(buf)
        elif isinstance(data, pil_image.Image):
            self._image = data
        elif util.is_pytorch_tensor_typename(util.get_full_typename(data)):
            if hasattr(data, "requires_grad") and data.requires_grad:
                data = data.detach()  # type: ignore
            if hasattr(data, "dtype") and str(data.dtype) == "torch.uint8":
                data = data.to(float)  # type: ignore [union-attr]
            mode = mode or self.guess_mode(data, file_type)
            data = data.permute(1, 2, 0).cpu().numpy()  # type: ignore [union-attr]

            _warn_on_invalid_data_range(data, normalize)

            data = _guess_and_rescale_to_0_255(data) if normalize else data  # type: ignore [arg-type]
            data = _convert_to_uint8(data)

            if data.ndim > 2:
                data = data.squeeze()

            self._image = pil_image.fromarray(
                data,
                mode=mode,
            )
        else:
            if hasattr(data, "numpy"):  # TF data eager tensors
                data = data.numpy()
            if data.ndim > 2:  # type: ignore [union-attr]
                # get rid of trivial dimensions as a convenience
                data = data.squeeze()  # type: ignore [union-attr]

            _warn_on_invalid_data_range(data, normalize)  # type: ignore [arg-type]

            mode = mode or self.guess_mode(data, file_type)
            data = _guess_and_rescale_to_0_255(data) if normalize else data  # type: ignore [arg-type]
            data = _convert_to_uint8(data)  # type: ignore [arg-type]
            self._image = pil_image.fromarray(
                data,
                mode=mode,
            )

        assert self._image is not None
        self._image.save(tmp_path, transparency=None)
        self._set_file(tmp_path, is_tmp=True)

    @classmethod
    def from_json(
        cls: Type["Image"], json_obj: dict, source_artifact: "Artifact"
    ) -> "Image":
        """Factory method to create an Audio object from a JSON object.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        classes: Optional[Classes] = None
        if json_obj.get("classes") is not None:
            value = source_artifact.get(json_obj["classes"]["path"])
            assert isinstance(value, (type(None), Classes))
            classes = value

        masks = json_obj.get("masks")
        _masks: Optional[Dict[str, ImageMask]] = None
        if masks:
            _masks = {}
            for key in masks:
                _masks[key] = ImageMask.from_json(masks[key], source_artifact)
                _masks[key]._set_artifact_source(source_artifact)
                _masks[key]._key = key

        boxes = json_obj.get("boxes")
        _boxes: Optional[Dict[str, BoundingBoxes2D]] = None
        if boxes:
            _boxes = {}
            for key in boxes:
                _boxes[key] = BoundingBoxes2D.from_json(boxes[key], source_artifact)
                _boxes[key]._key = key

        return cls(
            source_artifact.get_entry(json_obj["path"]).download(),
            caption=json_obj.get("caption"),
            grouping=json_obj.get("grouping"),
            classes=classes,
            boxes=_boxes,
            masks=_masks,
        )

    @classmethod
    def get_media_subdir(cls: Type["Image"]) -> str:
        """Get media subdirectory.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        return os.path.join("media", "images")

    def bind_to_run(
        self,
        run: "wandb.Run",
        key: Union[int, str],
        step: Union[int, str],
        id_: Optional[Union[int, str]] = None,
        ignore_copy_err: Optional[bool] = None,
    ) -> None:
        """Bind this object to a run.

        <!-- lazydoc-ignore: internal -->
        """
        # For Images, we are going to avoid copying the image file to the run.
        # We should make this common functionality for all media types, but that
        # requires a broader UI refactor. This model can easily be moved to the
        # higher level Media class, but that will require every UI surface area
        # that depends on the `path` to be able to instead consume
        # `artifact_path`. I (Tim) think the media panel makes up most of this
        # space, but there are also custom charts, and maybe others. Let's
        # commit to getting all that fixed up before moving this to  the top
        # level Media class.
        if self.path_is_reference(self._path):
            raise ValueError(
                "Image media created by a reference to external storage cannot currently be added to a run"
            )

        if (
            not _server_accepts_artifact_path(run)
            or self._get_artifact_entry_ref_url() is None
        ):
            super().bind_to_run(run, key, step, id_, ignore_copy_err=ignore_copy_err)
        if self._boxes is not None:
            for i, k in enumerate(self._boxes):
                id_ = f"{id_}{i}" if id_ is not None else None
                self._boxes[k].bind_to_run(
                    run, key, step, id_, ignore_copy_err=ignore_copy_err
                )

        if self._masks is not None:
            for i, k in enumerate(self._masks):
                id_ = f"{id_}{i}" if id_ is not None else None
                self._masks[k].bind_to_run(
                    run, key, step, id_, ignore_copy_err=ignore_copy_err
                )

    def to_json(self, run_or_artifact: Union["wandb.Run", "Artifact"]) -> dict:
        """Returns the JSON representation expected by the backend.

        <!-- lazydoc-ignore: internal -->
        """
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = Image._log_type
        json_dict["format"] = self.format

        if self._width is not None:
            json_dict["width"] = self._width
        if self._height is not None:
            json_dict["height"] = self._height
        if self._grouping:
            json_dict["grouping"] = self._grouping

        if isinstance(run_or_artifact, wandb.Artifact):
            artifact = run_or_artifact
            if (
                self._masks is not None or self._boxes is not None
            ) and self._classes is None:
                raise ValueError(
                    "classes must be passed to wandb.Image which have masks or bounding boxes when adding to artifacts"
                )

            if self._classes is not None:
                class_id = hashutil._md5(
                    str(self._classes._class_set).encode("utf-8")
                ).hexdigest()
                class_name = os.path.join(
                    "media",
                    "classes",
                    class_id + "_cls",
                )
                classes_entry = artifact.add(self._classes, class_name)
                json_dict["classes"] = {
                    "type": "classes-file",
                    "path": classes_entry.path,
                    "digest": classes_entry.digest,
                }

        elif not isinstance(run_or_artifact, wandb.Run):
            raise TypeError("to_json accepts wandb.Run or wandb_artifact.Artifact")

        if self._boxes:
            json_dict["boxes"] = {
                k: box.to_json(run_or_artifact) for (k, box) in self._boxes.items()
            }
        if self._masks:
            json_dict["masks"] = {
                k: mask.to_json(run_or_artifact) for (k, mask) in self._masks.items()
            }
        return json_dict

    def guess_mode(
        self,
        data: Union["np.ndarray", "torch.Tensor"],
        file_type: Optional[str] = None,
    ) -> str:
        """Guess what type of image the np.array is representing.

        <!-- lazydoc-ignore: internal -->
        """
        # TODO: do we want to support dimensions being at the beginning of the array?
        ndims = data.ndim
        if util.is_pytorch_tensor_typename(util.get_full_typename(data)):
            # Torch tenors typically have the channels dimension first
            num_channels = data.shape[0]
        else:
            num_channels = data.shape[-1]

        if ndims == 2 or num_channels == 1:
            return "L"
        elif num_channels == 3:
            return "RGB"
        elif num_channels == 4:
            if file_type in ["jpg", "jpeg"]:
                wandb.termwarn(
                    "JPEG format does not support transparency. "
                    "Ignoring alpha channel.",
                    repeat=False,
                )
                return "RGB"
            else:
                return "RGBA"
        else:
            raise ValueError(
                f"Un-supported shape for image conversion {list(data.shape)}"
            )

    @classmethod
    def seq_to_json(
        cls: Type["Image"],
        seq: Sequence["BatchableMedia"],
        run: "wandb.Run",
        key: str,
        step: Union[int, str],
    ) -> dict:
        """Convert a sequence of Image objects to a JSON representation.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        if TYPE_CHECKING:
            seq = cast(Sequence["Image"], seq)

        jsons = [obj.to_json(run) for obj in seq]

        media_dir = cls.get_media_subdir()

        for obj in jsons:
            expected = LogicalPath(media_dir)
            if "path" in obj and not obj["path"].startswith(expected):
                raise ValueError(
                    "Files in an array of Image's must be in the {} directory, not {}".format(
                        cls.get_media_subdir(), obj["path"]
                    )
                )

        num_images_to_log = len(seq)
        width, height = seq[0].image.size  # type: ignore
        format = jsons[0]["format"]

        def size_equals_image(image: "Image") -> bool:
            img_width, img_height = image.image.size  # type: ignore
            return img_width == width and img_height == height

        sizes_match = all(size_equals_image(img) for img in seq)
        if not sizes_match:
            logging.warning(
                "Images sizes do not match. This will causes images to be display incorrectly in the UI."
            )

        meta = {
            "_type": "images/separated",
            "width": width,
            "height": height,
            "format": format,
            "count": num_images_to_log,
        }
        if _server_accepts_image_filenames(run):
            meta["filenames"] = [
                obj.get("path", obj.get("artifact_path")) for obj in jsons
            ]
        else:
            wandb.termwarn(
                "Unable to log image array filenames. In some cases, this can prevent images from being "
                "viewed in the UI. Please upgrade your wandb server",
                repeat=False,
            )

        captions = Image.all_captions(seq)

        if captions:
            meta["captions"] = captions

        all_masks = Image.all_masks(seq, run, key, step)

        if all_masks:
            meta["all_masks"] = all_masks

        all_boxes = Image.all_boxes(seq, run, key, step)

        if all_boxes:
            meta["all_boxes"] = all_boxes

        return meta

    @classmethod
    def all_masks(
        cls: Type["Image"],
        images: Sequence["Image"],
        run: "wandb.Run",
        run_key: str,
        step: Union[int, str],
    ) -> Union[List[Optional[dict]], bool]:
        """Collect all masks from a list of images.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        all_mask_groups: List[Optional[dict]] = []
        for image in images:
            if image._masks:
                mask_group = {}
                for k in image._masks:
                    mask = image._masks[k]
                    mask_group[k] = mask.to_json(run)
                all_mask_groups.append(mask_group)
            else:
                all_mask_groups.append(None)
        if all_mask_groups and not all(x is None for x in all_mask_groups):
            return all_mask_groups
        else:
            return False

    @classmethod
    def all_boxes(
        cls: Type["Image"],
        images: Sequence["Image"],
        run: "wandb.Run",
        run_key: str,
        step: Union[int, str],
    ) -> Union[List[Optional[dict]], bool]:
        """Collect all boxes from a list of images.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        all_box_groups: List[Optional[dict]] = []
        for image in images:
            if image._boxes:
                box_group = {}
                for k in image._boxes:
                    box = image._boxes[k]
                    box_group[k] = box.to_json(run)
                all_box_groups.append(box_group)
            else:
                all_box_groups.append(None)
        if all_box_groups and not all(x is None for x in all_box_groups):
            return all_box_groups
        else:
            return False

    @classmethod
    def all_captions(
        cls: Type["Image"], images: Sequence["Media"]
    ) -> Union[bool, Sequence[Optional[str]]]:
        """Get captions from a list of images.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        return cls.captions(images)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Image):
            return False
        else:
            if self.path_is_reference(self._path) and self.path_is_reference(
                other._path
            ):
                return self._path == other._path
            self_image = self.image
            other_image = other.image
            if self_image is not None:
                self_image = list(self_image.getdata())  # type: ignore
            if other_image is not None:
                other_image = list(other_image.getdata())  # type: ignore

            return (
                self._grouping == other._grouping
                and self._caption == other._caption
                and self._width == other._width
                and self._height == other._height
                and self_image == other_image
                and self._classes == other._classes
            )

    def to_data_array(self) -> List[Any]:
        """Convert to data array.

        <!-- lazydoc-ignore: internal -->
        """
        res = []
        if self.image is not None:
            data = list(self.image.getdata())
            for i in range(self.image.height):
                res.append(data[i * self.image.width : (i + 1) * self.image.width])
        self._free_ram()
        return res

    def _free_ram(self) -> None:
        if self._path is not None:
            self._image = None

    @property
    def image(self) -> Optional["PILImage"]:
        if self._image is None:
            if self._path is not None and not self.path_is_reference(self._path):
                pil_image = util.get_module(
                    "PIL.Image",
                    required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
                )
                self._image = pil_image.open(self._path)
                self._image.load()
        return self._image


# Custom dtypes for typing system
class _ImageFileType(_dtypes.Type):
    name = "image-file"
    legacy_names = ["wandb.Image"]
    types = [Image]

    def __init__(
        self,
        box_layers=None,
        box_score_keys=None,
        mask_layers=None,
        class_map=None,
        **kwargs,
    ):
        box_layers = box_layers or {}
        box_score_keys = box_score_keys or []
        mask_layers = mask_layers or {}
        class_map = class_map or {}

        if isinstance(box_layers, _dtypes.ConstType):
            box_layers = box_layers._params["val"]
        if not isinstance(box_layers, dict):
            raise TypeError("box_layers must be a dict")
        else:
            box_layers = _dtypes.ConstType(
                {layer_key: set(box_layers[layer_key]) for layer_key in box_layers}
            )

        if isinstance(mask_layers, _dtypes.ConstType):
            mask_layers = mask_layers._params["val"]
        if not isinstance(mask_layers, dict):
            raise TypeError("mask_layers must be a dict")
        else:
            mask_layers = _dtypes.ConstType(
                {layer_key: set(mask_layers[layer_key]) for layer_key in mask_layers}
            )

        if isinstance(box_score_keys, _dtypes.ConstType):
            box_score_keys = box_score_keys._params["val"]
        if not isinstance(box_score_keys, list) and not isinstance(box_score_keys, set):
            raise TypeError("box_score_keys must be a list or a set")
        else:
            box_score_keys = _dtypes.ConstType(set(box_score_keys))

        if isinstance(class_map, _dtypes.ConstType):
            class_map = class_map._params["val"]
        if not isinstance(class_map, dict):
            raise TypeError("class_map must be a dict")
        else:
            class_map = _dtypes.ConstType(class_map)

        self.params.update(
            {
                "box_layers": box_layers,
                "box_score_keys": box_score_keys,
                "mask_layers": mask_layers,
                "class_map": class_map,
            }
        )

    def assign_type(self, wb_type=None):
        if isinstance(wb_type, _ImageFileType):
            box_layers_self = self.params["box_layers"].params["val"] or {}
            box_score_keys_self = self.params["box_score_keys"].params["val"] or []
            mask_layers_self = self.params["mask_layers"].params["val"] or {}
            class_map_self = self.params["class_map"].params["val"] or {}

            box_layers_other = wb_type.params["box_layers"].params["val"] or {}
            box_score_keys_other = wb_type.params["box_score_keys"].params["val"] or []
            mask_layers_other = wb_type.params["mask_layers"].params["val"] or {}
            class_map_other = wb_type.params["class_map"].params["val"] or {}

            # Merge the class_ids from each set of box_layers
            box_layers = {
                str(key): set(
                    list(box_layers_self.get(key, []))
                    + list(box_layers_other.get(key, []))
                )
                for key in set(
                    list(box_layers_self.keys()) + list(box_layers_other.keys())
                )
            }

            # Merge the class_ids from each set of mask_layers
            mask_layers = {
                str(key): set(
                    list(mask_layers_self.get(key, []))
                    + list(mask_layers_other.get(key, []))
                )
                for key in set(
                    list(mask_layers_self.keys()) + list(mask_layers_other.keys())
                )
            }

            # Merge the box score keys
            box_score_keys = set(list(box_score_keys_self) + list(box_score_keys_other))

            # Merge the class_map
            class_map = {
                str(key): class_map_self.get(key, class_map_other.get(key, None))
                for key in set(
                    list(class_map_self.keys()) + list(class_map_other.keys())
                )
            }

            return _ImageFileType(box_layers, box_score_keys, mask_layers, class_map)

        return _dtypes.InvalidType()

    @classmethod
    def from_obj(cls, py_obj):
        if not isinstance(py_obj, Image):
            raise TypeError("py_obj must be a wandb.Image")
        else:
            if hasattr(py_obj, "_boxes") and py_obj._boxes:
                box_layers = {
                    str(key): set(py_obj._boxes[key]._class_labels.keys())
                    for key in py_obj._boxes.keys()
                }
                box_score_keys = {
                    key
                    for val in py_obj._boxes.values()
                    for box in val._val
                    for key in box.get("scores", {}).keys()
                }

            else:
                box_layers = {}
                box_score_keys = set()

            if hasattr(py_obj, "_masks") and py_obj._masks:
                mask_layers = {
                    str(key): set(
                        py_obj._masks[key]._val["class_labels"].keys()
                        if hasattr(py_obj._masks[key], "_val")
                        else []
                    )
                    for key in py_obj._masks.keys()
                }
            else:
                mask_layers = {}

            if hasattr(py_obj, "_classes") and py_obj._classes:
                class_set = {
                    str(item["id"]): item["name"] for item in py_obj._classes._class_set
                }
            else:
                class_set = {}

            return cls(box_layers, box_score_keys, mask_layers, class_set)


_dtypes.TypeRegistry.add(_ImageFileType)
