import hashlib
import os
import pathlib
import re
import shutil
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Type, Union, cast

import wandb
from wandb import util
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.paths import LogicalPath

from .wb_value import WBValue

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np

    from wandb.sdk.artifacts.artifact import Artifact


def _wb_filename(
    key: Union[str, int], step: Union[str, int], id: Union[str, int], extension: str
) -> str:
    r"""Generates a safe filename/path for storing media files, using the provided key, step, and id.

    If the key contains slashes (e.g. 'images/cats/fluffy.jpg'), subdirectories will be created:
        media/
          images/
            cats/
              fluffy.jpg_step_id.ext

    Args:
        key: Name/path for the media file
        step: Training step number
        id: Unique identifier
        extension: File extension (e.g. '.jpg', '.mp3')

    Returns:
        A sanitized filename string in the format: key_step_id.extension

    Raises:
        ValueError: If running on Windows and the key contains invalid filename characters
                   (\\, :, *, ?, ", <, >, |)
    """
    key = util.make_file_path_upload_safe(str(key))

    return f"{str(key)}_{str(step)}_{str(id)}{extension}"


class Media(WBValue):
    """A WBValue stored as a file outside JSON that can be rendered in a media panel.

    If necessary, we move or copy the file into the Run's media directory so that it
    gets uploaded.
    """

    _path: Optional[str]
    _run: Optional["wandb.Run"]
    _caption: Optional[str]
    _is_tmp: Optional[bool]
    _extension: Optional[str]
    _sha256: Optional[str]
    _size: Optional[int]

    def __init__(self, caption: Optional[str] = None) -> None:
        super().__init__()
        self._path = None
        # The run under which this object is bound, if any.
        self._run = None
        self._caption = caption

    def _set_file(
        self,
        path: str,
        is_tmp: bool = False,
        extension: Optional[str] = None,
    ) -> None:
        self._path = path
        self._is_tmp = is_tmp
        self._extension = extension
        assert extension is None or path.endswith(extension), (
            f'Media file extension "{extension}" must occur at the end of path "{path}".'
        )

        with open(self._path, "rb") as f:
            self._sha256 = hashlib.sha256(f.read()).hexdigest()
        self._size = os.path.getsize(self._path)

    @classmethod
    def get_media_subdir(cls: Type["Media"]) -> str:
        raise NotImplementedError

    @staticmethod
    def captions(
        media_items: Sequence["Media"],
    ) -> Union[bool, Sequence[Optional[str]]]:
        if media_items[0]._caption is not None:
            return [m._caption for m in media_items]
        else:
            return False

    def is_bound(self) -> bool:
        return self._run is not None

    def file_is_set(self) -> bool:
        return self._path is not None and self._sha256 is not None

    def bind_to_run(
        self,
        run: "wandb.Run",
        key: Union[int, str],
        step: Union[int, str],
        id_: Optional[Union[int, str]] = None,
        ignore_copy_err: Optional[bool] = None,
    ) -> None:
        """Bind this object to a particular Run.

        Calling this function is necessary so that we have somewhere specific to put the
        file associated with this object, from which other Runs can refer to it.
        """
        assert self.file_is_set(), "bind_to_run called before _set_file"

        # The following two assertions are guaranteed to pass
        # by definition file_is_set, but are needed for
        # mypy to understand that these are strings below.
        assert isinstance(self._path, str)
        assert isinstance(self._sha256, str)

        assert run is not None, 'Argument "run" must not be None.'
        self._run = run

        if self._extension is None:
            _, extension = os.path.splitext(os.path.basename(self._path))
        else:
            extension = self._extension

        if id_ is None:
            id_ = self._sha256[:20]

        file_path = _wb_filename(key, step, id_, extension)
        media_path = os.path.join(self.get_media_subdir(), file_path)
        new_path = os.path.join(self._run.dir, media_path)
        filesystem.mkdir_exists_ok(os.path.dirname(new_path))

        if self._is_tmp:
            shutil.move(self._path, new_path)
            self._path = new_path
            self._is_tmp = False
            run._publish_file(media_path)
        else:
            try:
                shutil.copy(self._path, new_path)
            except shutil.SameFileError:
                if not ignore_copy_err:
                    raise
            self._path = new_path
            run._publish_file(media_path)

    def to_json(self, run: Union["wandb.Run", "Artifact"]) -> dict:
        """Serialize the object into a JSON blob.

        Uses run or artifact to store additional data. If `run_or_artifact` is a
        wandb.Run then `self.bind_to_run()` must have been previously been called.

        Args:
            run_or_artifact (wandb.Run | wandb.Artifact): the Run or Artifact for which
                this object should be generating JSON for - this is useful to store
                additional data if needed.

        Returns:
            dict: JSON representation
        """
        # NOTE: uses of Audio in this class are a temporary hack -- when Ref support moves up
        # into Media itself we should get rid of them
        from wandb import Image
        from wandb.data_types import Audio

        json_obj: Dict[str, Any] = {}

        if self._caption is not None:
            json_obj["caption"] = self._caption

        if isinstance(run, wandb.Run):
            json_obj.update(
                {
                    "_type": "file",  # TODO(adrian): This isn't (yet) a real media type we support on the frontend.
                    "sha256": self._sha256,
                    "size": self._size,
                }
            )

            artifact_entry_url = self._get_artifact_entry_ref_url()
            if artifact_entry_url is not None:
                json_obj["artifact_path"] = artifact_entry_url
            artifact_entry_latest_url = self._get_artifact_entry_latest_ref_url()
            if artifact_entry_latest_url is not None:
                json_obj["_latest_artifact_path"] = artifact_entry_latest_url

            if artifact_entry_url is None or self.is_bound():
                assert self.is_bound(), (
                    f"Value of type {type(self).__name__} must be bound to a run with bind_to_run() before being serialized to JSON."
                )

                assert self._run is run, (
                    "We don't support referring to media files across runs."
                )

                # The following two assertions are guaranteed to pass
                # by definition is_bound, but are needed for
                # mypy to understand that these are strings below.
                assert isinstance(self._path, str)
                json_obj["path"] = LogicalPath(
                    os.path.relpath(self._path, self._run.dir)
                )

        elif isinstance(run, wandb.Artifact):
            if self.file_is_set():
                # The following two assertions are guaranteed to pass
                # by definition of the call above, but are needed for
                # mypy to understand that these are strings below.
                assert isinstance(self._path, str)
                assert isinstance(self._sha256, str)
                artifact = run  # Checks if the concrete image has already been added to this artifact
                name = artifact.get_added_local_path_name(self._path)
                if name is None:
                    if self._is_tmp:
                        name = os.path.join(
                            self.get_media_subdir(), os.path.basename(self._path)
                        )
                    else:
                        # If the files is not temporary, include the first 8 characters of the file's SHA256 to
                        # avoid name collisions. This way, if there are two images `dir1/img.png` and `dir2/img.png`
                        # we end up with a unique path for each.
                        name = os.path.join(
                            self.get_media_subdir(),
                            self._sha256[:20],
                            os.path.basename(self._path),
                        )

                    # if not, check to see if there is a source artifact for this object
                    if (
                        self._artifact_source is not None
                        # and self._artifact_source.artifact != artifact
                    ):
                        default_root = self._artifact_source.artifact._default_root()
                        # if there is, get the name of the entry (this might make sense to move to a helper off artifact)
                        if self._path.startswith(default_root):
                            name = self._path[len(default_root) :]
                            name = name.lstrip(os.sep)

                        # Add this image as a reference
                        path = self._artifact_source.artifact.get_entry(name)
                        artifact.add_reference(path.ref_url(), name=name)
                    elif (
                        isinstance(self, Audio) or isinstance(self, Image)
                    ) and self.path_is_reference(self._path):
                        artifact.add_reference(self._path, name=name)
                    else:
                        entry = artifact.add_file(
                            self._path, name=name, is_tmp=self._is_tmp
                        )
                        name = entry.path

                json_obj["path"] = name
                json_obj["sha256"] = self._sha256
            json_obj["_type"] = self._log_type
        return json_obj

    @classmethod
    def from_json(
        cls: Type["Media"], json_obj: dict, source_artifact: "Artifact"
    ) -> "Media":
        """Likely will need to override for any more complicated media objects."""
        return cls(source_artifact.get_entry(json_obj["path"]).download())

    def __eq__(self, other: object) -> bool:
        """Likely will need to override for any more complicated media objects."""
        return (
            isinstance(other, self.__class__)
            and hasattr(self, "_sha256")
            and hasattr(other, "_sha256")
            and self._sha256 == other._sha256
        )

    @staticmethod
    def path_is_reference(path: Optional[Union[str, pathlib.Path]]) -> bool:
        if path is None or isinstance(path, pathlib.Path):
            return False

        return bool(path and re.match(r"^(gs|s3|https?)://", path))


class BatchableMedia(Media):
    """Media that is treated in batches.

    E.g. images and thumbnails. Apart from images, we just use these batches to help
    organize files by name in the media directory.
    """

    def __init__(
        self,
        caption: Optional[str] = None,
    ) -> None:
        super().__init__(caption=caption)

    @classmethod
    def seq_to_json(
        cls: Type["BatchableMedia"],
        seq: Sequence["BatchableMedia"],
        run: "wandb.Run",
        key: str,
        step: Union[int, str],
    ) -> dict:
        raise NotImplementedError


def _numpy_arrays_to_lists(
    payload: Union[dict, Sequence, "np.ndarray"],
) -> Union[Sequence, dict, str, int, float, bool]:
    # Casts all numpy arrays to lists so we don't convert them to histograms, primarily for Plotly

    if isinstance(payload, dict):
        res = {}
        for key, val in payload.items():
            res[key] = _numpy_arrays_to_lists(val)
        return res
    elif isinstance(payload, Sequence) and not isinstance(payload, str):
        return [_numpy_arrays_to_lists(v) for v in payload]
    elif util.is_numpy_array(payload):
        if TYPE_CHECKING:
            payload = cast("np.ndarray", payload)
        return [
            _numpy_arrays_to_lists(v)
            for v in (payload.tolist() if payload.ndim > 0 else [payload.tolist()])
        ]
    # Protects against logging non serializable objects
    elif isinstance(payload, Media):
        return str(payload.__class__.__name__)
    return payload  # type: ignore
