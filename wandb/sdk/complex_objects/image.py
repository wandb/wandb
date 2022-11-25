import io
import pathlib
from typing import TYPE_CHECKING, Optional, Union, List

try:
    from typing_extensions import Protocol, runtime_checkable
except ImportError:
    from typing import Protocol, runtime_checkable

from .image_mask import ImageMask
from .bounding_boxes_2d import BoundingBoxes2D
import PIL.Image

from .media import Media

if TYPE_CHECKING:
    import matplotlib.artist.Artist  # type: ignore
    import numpy as np
    import tensorflow as tf
    import torch


class Image(Media):
    """A wandb Image object."""

    RELATIVE_PATH = pathlib.Path("media") / "images"
    DEFAULT_FORMAT = "PNG"
    OBJ_TYPE = "image-file"

    _source_path: pathlib.Path
    _is_temp_path: bool
    _bind_path: Optional[pathlib.Path]

    _size: int
    _sha256: str
    _format: str

    _width: int
    _height: int

    _caption: Optional[str]
    _masks: List[ImageMask]
    _bounding_boxes: List[BoundingBoxes2D]
    _classes: dict

    def __init__(
        self,
        data_or_path,
        mode: Optional[str] = None,
        caption: Optional[str] = None,
        boxes: Optional[dict] = None,
        masks: Optional[dict] = None,
        classes=None,
    ) -> None:
        """Initialize a new wandb Image object."""

        if isinstance(data_or_path, PIL.Image.Image):
            self.from_pillow(data_or_path)
        elif isinstance(data_or_path, str):
            self.from_path(data_or_path)
        elif isinstance(data_or_path, pathlib.Path):
            self.from_path(data_or_path)
        elif isinstance(data_or_path, Image):
            self.from_image(data_or_path)
        elif isinstance(data_or_path, np.ndarray):
            self.from_numpy(data_or_path, mode=mode)
        elif isinstance(data_or_path, torch.Tensor):
            self.from_torch(data_or_path, mode=mode)
        elif isinstance(data_or_path, tf.Tensor):
            self.from_tensorflow(data_or_path, mode=mode)
        elif isinstance(data_or_path, matplotlib.artist.Artist):
            self.from_matplotlib(data_or_path)
        else:
            raise ValueError(
                "Image must be initialized with a path, PIL.Image, or bytes"
            )

        self._caption = caption

        self._bounding_boxes = []
        if boxes is not None:
            self.add_bounding_boxes(boxes)

        self._masks = []
        if masks is not None:
            self.add_masks(masks)

        self._classes = dict()
        # if classes is not None:
        self.add_classes(classes)

    def to_json(self) -> dict:
        """Serialize this image to json.

        Returns:
            dict: The json representation of this image.
        """
        serialized = super().to_json()
        serialized["format"] = self._format
        if self._width is not None:
            serialized["width"] = self._width
        if self._height is not None:
            serialized["height"] = self._height
        if self._caption is not None:
            serialized["caption"] = self._caption
        if self._bounding_boxes:
            serialized["boxes"] = {
                bounding_box._name: bounding_box.to_json()
                for bounding_box in self._bounding_boxes
            }
        if self._masks:
            serialized["masks"] = {k: mask.to_json() for k, mask in self._masks.items()}
        return serialized

    def bind_to_run(
        self, interface, root_dir: pathlib.Path, *prefix, name: Optional[str] = None
    ) -> None:
        """Bind this image to a run.

        Args:
            interface: The interface to the run.
            start: The path to the run directory.
            prefix: A list of path components to prefix to the image path.
            name: The name of the image.
        """

        super().bind_to_run(
            interface,
            root_dir,
            *prefix,
            name or self._sha256[:20],
            suffix=f".{self._format}",
        )

        for i, mask in enumerate(self._masks):
            name = f"{name}{i}" if name is not None else None
            mask.bind_to_run(interface, root_dir, *prefix, name=name)

        for i, bounding_box in enumerate(self._bounding_boxes):
            name = f"{name}{i}" if name is not None else None
            bounding_box.bind_to_run(interface, root_dir, *prefix, name=name)

    def add_masks(self, masks: dict) -> None:
        """Add masks to this image.

        Args:
            masks (dict): The masks to add to this image.
        """
        for name, mask in masks.items():
            if isinstance(mask, ImageMask):
                self._masks.append(mask)
            elif isinstance(mask, dict):
                self._masks.append(ImageMask(mask, name=name))
            else:
                raise ValueError(
                    "Image masks must be initialized ImageMask objects or dicts"
                )

    def add_bounding_boxes(self, bounding_boxes: dict) -> None:
        """Add bounding boxes to this image.

        Args:
            bounding_boxes (dict): The bounding boxes to add to this image.
        """
        for name, bounding_box in bounding_boxes.items():
            if isinstance(bounding_box, BoundingBoxes2D):
                self._bounding_boxes.append(bounding_box)
            elif isinstance(bounding_box, dict):
                self._bounding_boxes.append(BoundingBoxes2D(bounding_box, name=name))
            else:
                raise ValueError(
                    "Image bounding boxes must be initialized BoundingBoxes2D objects or dicts"
                )

    def add_classes(self, classes) -> None:
        """Add classes to this image.

        Args:
            classes (dict): The classes to add to this image.
        """
        self._classes = classes

    def from_path(self, path: Union[str, pathlib.Path]) -> None:
        """Create an image from a path.

        Args:
            path (Union[str, pathlib.Path]): The path to the image.
        """

        path = pathlib.Path(path).absolute()
        self._source_path = path
        self._is_temp_path = False
        self._format = path.suffix[1:].lower()
        with PIL.Image.open(path) as image:
            image.load()
            self._width = image.width
            self._height = image.height
        self._size = self._source_path.stat().st_size
        self._sha256 = self._compute_sha256(self._source_path)

    def from_pillow(self, image: "PIL.Image.Image") -> None:
        """Create an image from a pillow image.

        Args:
            image (PIL.Image.Image): The pillow image to create this image from.
        """
        self._format = (image.format or self.DEFAULT_FORMAT).lower()
        self._width = image.width
        self._height = image.height
        self._source_path = self._generate_temp_path(f".{self._format}")
        self._is_temp_path = True
        image.save(
            self._source_path,
            format=self._format,
            transparency=None,
        )
        self._size = self._source_path.stat().st_size
        self._sha256 = self._compute_sha256(self._source_path)

    def from_numpy(self, array: "np.ndarray", mode: Optional[str] = None) -> None:
        """Create an image from a numpy array.

        Args:
            array (np.ndarray): The numpy array to create this image from.
            mode (Optional[str], optional): The mode to create this image in. Defaults to None.
        """
        import torch

        if isinstance(array, torch.Tensor):
            import torchvision.utils

            if hasattr(array, "detach"):
                array = array.detach()

            tensor = torchvision.utils.make_grid(array, normalize=True)
            tensor = tensor.permute(1, 2, 0).mul(255).clamp(0, 255).byte().cpu().numpy()
        else:
            tensor = array.__array__()
            if tensor.ndim > 2:
                tensor = tensor.squeeze()
            min_value = tensor.min()
            if min_value < 0:
                tensor = (tensor - min_value) / tensor.ptp() * 255
            if tensor.max() <= 1:
                tensor = (tensor * 255).astype("int32")
            tensor = tensor.clip(0, 255).astype("uint8")

        image = PIL.Image.fromarray(tensor, mode=mode)
        self.from_pillow(image)

    def from_torch(self, tensor: "torch.Tensor", mode: Optional[str] = None) -> None:
        """Create an image from a torch tensor.

        Args:
            tensor (torch.Tensor): The torch tensor to create this image from.
            mode (Optional[str], optional): The mode to create this image in. Defaults to None.
        """

        array = tensor.numpy()
        self.from_numpy(array, mode=mode)

    def from_tensorflow(self, tensor: "tf.Tensor", mode: Optional[str] = None) -> None:
        """Create an image from a tensorflow tensor.

        Args:
            tensor (tf.Tensor): The tensorflow tensor to create this image from.
            mode (Optional[str], optional): The mode to create this image in. Defaults to None.
        """
        array = tensor.numpy()  # type: ignore
        self.from_numpy(array, mode=mode)

    def from_matplotlib(
        self, figure: "matplotlib.artist.Artist", format: Optional[str] = None
    ) -> None:
        """Create an image from a matplotlib figure.

        Args:
            figure (matplotlib.figure.Figure): The matplotlib figure to create this image from.
            format (Optional[str], optional): The format to save this image in. Defaults to None.
        """
        buf = io.BytesIO()
        format = format or self.DEFAULT_FORMAT
        figure.savefig(buf, format=format)
        self.from_buffer(buf)

    def from_buffer(self, buf: io.BytesIO) -> None:
        """Create an image from a buffer.

        Args:
            buf (io.BytesIO): The buffer to create this image from.
        """

        with PIL.Image.open(buf) as image:
            self.from_pillow(image)

    def from_image(self, image: "Image") -> None:
        """Create an image from another image.

        Args:
            image (Image): The image to create this image from.

        Returns:
            Image: The image from this image.
        """

        exculded = {"_caption", "_masks", "_bounding_boxes", "_classes"}
        for k, v in image.__dict__.items():
            if k not in exculded:
                setattr(self, k, v)
