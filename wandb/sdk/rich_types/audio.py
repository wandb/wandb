from .media import Media
import pathlib
from typing import Optional, Union
import soundfile


class Audio(Media):

    OBJ_TYPE = "audio-file"
    RELATIVE_PATH = pathlib.Path("media") / "audio"
    DEFAULT_FORMAT = "WAV"

    _source_path: pathlib.Path
    _is_temp_path: bool
    _bind_path: Optional[pathlib.Path]
    _size: int
    _sha256: str
    _format: str

    def __init__(
        self,
        data_or_path,
        caption: Optional[str] = None,
        sample_rate: Optional[str] = None,
    ) -> None:
        if isinstance(data_or_path, (str, pathlib.Path)):
            self.from_path(data_or_path)
        else:
            self.from_array(data_or_path, sample_rate=sample_rate)

        self._caption = caption

    def from_path(self, path: Union[str, pathlib.Path]) -> None:
        self._source_path = pathlib.Path(path)
        self._is_temp_path = False
        self._sha256 = self._compute_sha256(self._source_path)
        self._size = self._source_path.stat().st_size
        self._format = self._source_path.suffix[1:].upper()

    def from_array(
        self,
        data,
        sample_rate: Optional[str] = None,
    ) -> None:

        assert sample_rate is not None, "sample_rate must be specified"

        self._format = self.DEFAULT_FORMAT.lower()
        self._source_path = self._generate_temp_path(suffix=f".{self._format}")
        self._is_temp_path = True
        soundfile.write(self._source_path, data, sample_rate)
        self._sha256 = self._compute_sha256(self._source_path)
        self._size = self._source_path.stat().st_size

    def bind_to_run(
        self, interface, start: pathlib.Path, *prefix, name: Optional[str] = None
    ) -> None:
        """
        Bind this audio object to a run.

        Args:
            interface: The interface to the run.
            start: The path to the run directory.
            prefix: A list of path components to prefix to the audio object path.
            name: The name of the audio object.
        """

        return super().bind_to_run(
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
            "caption": self._caption,
            "path": str(self._bind_path),
        }
