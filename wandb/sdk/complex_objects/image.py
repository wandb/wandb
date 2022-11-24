from typing import TYPE_CHECKING, Optional
import pathlib
import hashlib
import io

from wandb import util


import PIL.Image

if TYPE_CHECKING:  # pragma: no cover
    import torch
    import tensorflow as tf
    import numpy as np


import tempfile

MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")


class Image:
    """A wandb Image object."""

    RELATIVE_PATH = pathlib.Path("media") / "images"
    DEFAULT_FORMAT = "PNG"
    TYPE = "image-file"

    format: Optional[str]
    width: Optional[int]
    height: Optional[int]
    _path: Optional["pathlib.Path"]
    _path_is_tmp: bool
    _sha256: Optional[str]
    _size: Optional[int]

    def __init__(self, path_or_data) -> None:
        # , mode: str

        self._path = None
        self._path_is_tmp = False
        self._from(path_or_data)

        assert self._path is not None
        self._size = self._path.stat().st_size
        with open(self._path, "rb") as f:
            self._sha256 = hashlib.sha256(f.read()).hexdigest()

    def _from(self, path_or_data) -> None:
        if isinstance(path_or_data, str):
            self._from_string(path_or_data)
        elif isinstance(path_or_data, pathlib.Path):
            self._from_path(path_or_data)
        elif isinstance(path_or_data, PIL.Image.Image):
            self._from_pil(path_or_data)
        elif isinstance(path_or_data, bytes):
            self._from_bytes(path_or_data)
        elif isinstance(path_or_data, torch.Tensor):
            self._from_torch(path_or_data)
        elif isinstance(path_or_data, tf.Tensor):
            self._from_tensorflow(path_or_data)
        elif isinstance(path_or_data, np.ndarray):
            self._from_numpy(path_or_data)
        else:
            raise ValueError("Invalid image type")

    def _from_image(self, image: "wandb.Image") -> None:
        pass

    def _from_matplotlib(self, figure: "matplotlib.figure.Figure") -> None:
        pass

    def _from_string(self, path: str) -> None:
        self._from_path(pathlib.Path(path))

    def _from_path(self, path: pathlib.Path) -> None:
        self._path = path

        with PIL.Image.open(path) as image:
            image.load()
            self._from_pil(image)

    def _from_pil(self, image: "PIL.Image.Image") -> None:
        self.format = (image.format or self.DEFAULT_FORMAT).lower()
        self.width = image.width
        self.height = image.height

        if self._path is None:
            path = MEDIA_TMP.name / pathlib.Path(util.generate_id()).with_suffix(
                f".{self.format}"
            )
            self._path = path
            image.save(path, format=self.format, transparency=None)
            self._path_is_tmp = True

    def _from_bytes(self, data: bytes) -> None:
        with PIL.Image.open(data) as image:
            self._from_pil(image)

    def _from_torch(self, tensor: "torch.Tensor") -> None:
        pass

    def _from_tensorflow(self, tensor: "tf.Tensor") -> None:
        pass

    def _from_numpy(self, array: "np.ndarray") -> None:
        pass

    # def _save_file_to_run(self, path: pathlib.Path, *namespace) -> pathlib.Path:
    #     """Save a file to the run directory.

    #     Args:
    #         path: The path to the file.
    #         namespace: The namespace to save the file to.

    #     Returns:
    #         pathlib.Path: The path to the saved file.
    #     """
    #     return self._save_to_run(path, *namespace)

    def _media_file_name(
        self, *namespace, sep="_", suffix: Optional[str] = None
    ) -> pathlib.Path:
        """Get the media file name for this image.

        Returns:
            str: The media file name for this image.
        """
        breakpoint()

        if suffix is None:
            suffix = self.format
        file_name = f"{sep.join(namespace)}.{suffix}"
        return file_name

    def _save_to_run(self, run_dir, key, step):

        import shutil

        media_path = pathlib.Path(run_dir) / self.RELATIVE_PATH
        media_path.mkdir(parents=True, exist_ok=True)
        file_name = self._media_file_name(key, str(step), self._sha256[:20])
        media_file = media_path / file_name

        assert self._path is not None
        if self._path_is_tmp:
            shutil.move(self._path, media_file)
            self._path_is_tmp = False
        else:
            shutil.copy(self._path, media_file)

        self._relative_path = media_file.relative_to(run_dir)
        return media_file

    def publish(self, interface, *namespace) -> None:
        """Publish this image to wandb.

        Args:
            interface: The interface to publish to.
        """
        import glob

        self._path = self._save_to_run(*namespace)

        files = {"files": [(glob.escape(str(self._path)), "now")]}

        interface.publish_files(files)

    def to_json(self) -> dict:
        """Serialize this image to json.

        Returns:
            dict: The json representation of this image.
        """
        return {
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "sha256": self._sha256,
            "size": self._size,
            "_type": self.TYPE,
            "path": str(self._relative_path),
        }

    # aws_prefix: str = "s3://"
    # gcs_prefix: str = "gs://"
    # azure_prefix: str = "az://"
