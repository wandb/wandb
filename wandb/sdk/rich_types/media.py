import glob
import hashlib
import pathlib
import shutil
import tempfile
from typing import Optional

from wandb import util

MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")


class Media:
    RELATIVE_PATH = pathlib.Path("media")
    FILE_SEP = "_"
    OBJ_TYPE = "file"

    _source_path: pathlib.Path
    _is_temp_path: bool
    _bind_path: Optional[pathlib.Path]
    _size: int
    _sha256: str

    def to_json(self) -> dict:
        """Serialize this media object to JSON.

        Returns:
            dict: A JSON representation of this media object.
        """
        return {
            "_type": self.OBJ_TYPE,
            "size": self._size,
            "sha256": self._sha256,
            "path": str(self._bind_path),
        }

    def bind_to_run(
        self, interface, start: pathlib.Path, *namespace, suffix: str = ""
    ) -> None:
        """Bind this media object to a run.

        Args:
            interface: The interface to the run.
            start: The path to the run directory.
            namespace: A list of path components to prefix to the media path.
            suffix: A suffix to append to the media path.
        """

        sep = self.FILE_SEP
        file_name = pathlib.Path(sep.join(namespace)).with_suffix(suffix)

        dest_path = pathlib.Path(start) / self.RELATIVE_PATH / file_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if self._is_temp_path:
            shutil.move(str(self._source_path), dest_path)
        else:
            shutil.copy(self._source_path, dest_path)

        self._source_path = dest_path
        self._is_temp_path = False
        self._bind_path = dest_path.relative_to(start)

        files = {"files": [(glob.escape(str(dest_path)), "now")]}
        interface.publish_files(files)

    @staticmethod
    def _generate_temp_path(suffix: str = "") -> pathlib.Path:
        """Get a temporary path for a media object.

        Args:
            suffix (str, optional): The suffix for this media object's path. Defaults to "".

        Returns:
            pathlib.Path: The temporary path for this media.
        """
        path = MEDIA_TMP.name / pathlib.Path(util.generate_id()).with_suffix(suffix)
        return path

    @staticmethod
    def _compute_sha256(file: pathlib.Path) -> str:
        """Get the sha256 hash for this media.

        Args:
            file (pathlib.Path): The path to the media.

        Returns:
            str: The sha256 hash for this media.
        """

        with open(file, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        return file_hash
