import hashlib
import logging
import os
from io import BytesIO
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Type, Union, cast
from urllib import parse

import wandb
from wandb import util
from wandb.sdk.lib import hashutil, runid
from wandb.sdk.lib.paths import LogicalPath

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

    from ..wandb_run import Run as LocalRun

    ImageDataType = Union[
        "matplotlib.artist.Artist", "PILImage", "TorchTensorType", "np.ndarray"
    ]
    ImageDataOrPathType = Union[str, "Image", ImageDataType]
    TorchTensorType = Union["torch.Tensor", "torch.Variable"]


def _server_accepts_image_filenames() -> bool:
    if util._is_offline():
        return True

    # Newer versions of wandb accept large image filenames arrays
    # but older versions would have issues with this.
    max_cli_version = util._get_max_cli_version()
    if max_cli_version is None:
        return False
    from wandb.util import parse_version

    accepts_image_filenames: bool = parse_version("0.12.10") <= parse_version(
        max_cli_version
    )
    return accepts_image_filenames


def _server_accepts_artifact_path() -> bool:
    from wandb.util import parse_version

    target_version = "0.12.14"
    max_cli_version = util._get_max_cli_version() if not util._is_offline() else None
    accepts_artifact_path: bool = max_cli_version is not None and parse_version(
        target_version
    ) <= parse_version(max_cli_version)
    return accepts_artifact_path


class Image(BatchableMedia):
    """Format images for logging to W&B.

    Arguments:
        data_or_path: (numpy array, string, io) Accepts numpy array of
            image data, or a PIL image. The class attempts to infer
            the data format and converts it.
        mode: (string) The PIL mode for an image. Most common are "L", "RGB",
            "RGBA". Full explanation at https://pillow.readthedocs.io/en/stable/handbook/concepts.html#modes
        caption: (string) Label for display of image.

    Note : When logging a `torch.Tensor` as a `wandb.Image`, images are normalized. If you do not want to normalize your images, please convert your tensors to a PIL Image.

    Examples:
        ### Create a wandb.Image from a numpy array
        <!--yeadoc-test:log-image-numpy-->
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

        ### Create a wandb.Image from a PILImage
        <!--yeadoc-test:log-image-pillow-->
        ```python
        import numpy as np
        from PIL import Image as PILImage
        import wandb

        with wandb.init() as run:
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3), dtype=np.uint8)
                pil_image = PILImage.fromarray(pixels, mode="RGB")
                image = wandb.Image(pil_image, caption=f"random field {i}")
                examples.append(image)
            run.log({"examples": examples})
        ```

        ### log .jpg rather than .png (default)
        <!--yeadoc-test:log-image-format-->
        ```python
        import numpy as np
        import wandb

        with wandb.init() as run:
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))
                image = wandb.Image(pixels, caption=f"random field {i}", file_type="jpg")
                examples.append(image)
            run.log({"examples": examples})
        ```
    """

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
    ) -> None:
        super().__init__()
        # TODO: We should remove grouping, it's a terrible name and I don't
        # think anyone uses it.

        self._grouping = None
        self._caption = None
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
        elif isinstance(data_or_path, str):
            if self.path_is_reference(data_or_path):
                self._initialize_from_reference(data_or_path)
            else:
                self._initialize_from_path(data_or_path)
        else:
            self._initialize_from_data(data_or_path, mode, file_type)
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

        if caption is not None:
            self._caption = caption

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
    ) -> None:
        pil_image = util.get_module(
            "PIL.Image",
            required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
        )
        if util.is_matplotlib_typename(util.get_full_typename(data)):
            buf = BytesIO()
            util.ensure_matplotlib_figure(data).savefig(buf, format="png")
            self._image = pil_image.open(buf, formats=["PNG"])
        elif isinstance(data, pil_image.Image):
            self._image = data
        elif util.is_pytorch_tensor_typename(util.get_full_typename(data)):
            vis_util = util.get_module(
                "torchvision.utils", "torchvision is required to render images"
            )
            if hasattr(data, "requires_grad") and data.requires_grad:
                data = data.detach()  # type: ignore
            if hasattr(data, "dtype") and str(data.dtype) == "torch.uint8":
                data = data.to(float)
            data = vis_util.make_grid(data, normalize=True)
            self._image = pil_image.fromarray(
                data.mul(255).clamp(0, 255).byte().permute(1, 2, 0).cpu().numpy()
            )
        else:
            if hasattr(data, "numpy"):  # TF data eager tensors
                data = data.numpy()
            if data.ndim > 2:
                data = data.squeeze()  # get rid of trivial dimensions as a convenience
            self._image = pil_image.fromarray(
                self.to_uint8(data), mode=mode or self.guess_mode(data)
            )
        accepted_formats = ["png", "jpg", "jpeg", "bmp"]
        if file_type is None:
            self.format = "png"
        else:
            self.format = file_type
        assert (
            self.format in accepted_formats
        ), f"file_type must be one of {accepted_formats}"
        tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + "." + self.format)
        assert self._image is not None
        self._image.save(tmp_path, transparency=None)
        self._set_file(tmp_path, is_tmp=True)

    @classmethod
    def from_json(
        cls: Type["Image"], json_obj: dict, source_artifact: "Artifact"
    ) -> "Image":
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
        return os.path.join("media", "images")

    def bind_to_run(
        self,
        run: "LocalRun",
        key: Union[int, str],
        step: Union[int, str],
        id_: Optional[Union[int, str]] = None,
        ignore_copy_err: Optional[bool] = None,
    ) -> None:
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
            not _server_accepts_artifact_path()
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

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        from wandb.sdk.wandb_run import Run

        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = Image._log_type
        json_dict["format"] = self.format

        if self._width is not None:
            json_dict["width"] = self._width
        if self._height is not None:
            json_dict["height"] = self._height
        if self._grouping:
            json_dict["grouping"] = self._grouping
        if self._caption:
            json_dict["caption"] = self._caption

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

        elif not isinstance(run_or_artifact, Run):
            raise ValueError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

        if self._boxes:
            json_dict["boxes"] = {
                k: box.to_json(run_or_artifact) for (k, box) in self._boxes.items()
            }
        if self._masks:
            json_dict["masks"] = {
                k: mask.to_json(run_or_artifact) for (k, mask) in self._masks.items()
            }
        return json_dict

    def guess_mode(self, data: "np.ndarray") -> str:
        """Guess what type of image the np.array is representing."""
        # TODO: do we want to support dimensions being at the beginning of the array?
        if data.ndim == 2:
            return "L"
        elif data.shape[-1] == 3:
            return "RGB"
        elif data.shape[-1] == 4:
            return "RGBA"
        else:
            raise ValueError(
                "Un-supported shape for image conversion {}".format(list(data.shape))
            )

    @classmethod
    def to_uint8(cls, data: "np.ndarray") -> "np.ndarray":
        """Convert image data to uint8.

        Convert floating point image on the range [0,1] and integer images on the range
        [0,255] to uint8, clipping if necessary.
        """
        np = util.get_module(
            "numpy",
            required="wandb.Image requires numpy if not supplying PIL Images: pip install numpy",
        )

        # I think it's better to check the image range vs the data type, since many
        # image libraries will return floats between 0 and 255

        # some images have range -1...1 or 0-1
        dmin = np.min(data)
        if dmin < 0:
            data = (data - np.min(data)) / np.ptp(data)
        if np.max(data) <= 1.0:
            data = (data * 255).astype(np.int32)

        # assert issubclass(data.dtype.type, np.integer), 'Illegal image format.'
        return data.clip(0, 255).astype(np.uint8)

    @classmethod
    def seq_to_json(
        cls: Type["Image"],
        seq: Sequence["BatchableMedia"],
        run: "LocalRun",
        key: str,
        step: Union[int, str],
    ) -> dict:
        """Combine a list of images into a meta dictionary object describing the child images."""
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
        if _server_accepts_image_filenames():
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
        run: "LocalRun",
        run_key: str,
        step: Union[int, str],
    ) -> Union[List[Optional[dict]], bool]:
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
        run: "LocalRun",
        run_key: str,
        step: Union[int, str],
    ) -> Union[List[Optional[dict]], bool]:
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
