import hashlib
import os
import pathlib
from typing import TYPE_CHECKING, Optional, Union

from wandb import util
from wandb.sdk.lib import filesystem, runid

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.media import BatchableMedia

if TYPE_CHECKING:
    import numpy as np


class Audio(BatchableMedia):
    """W&B class for audio clips."""

    _log_type = "audio-file"

    def __init__(
        self,
        data_or_path: Union[
            str,
            pathlib.Path,
            list,
            "np.ndarray",
        ],
        sample_rate: Optional[int] = None,
        caption: Optional[str] = None,
    ):
        """Accept a path to an audio file or a numpy array of audio data.

        Args:
            data_or_path: A path to an audio file or a NumPy array of audio data.
            sample_rate: Sample rate, required when passing in raw NumPy array of audio data.
            caption: Caption to display with audio.
        """
        super().__init__(caption=caption)
        self._duration = None
        self._sample_rate = sample_rate

        if isinstance(data_or_path, (str, pathlib.Path)):
            data_or_path = str(data_or_path)

            if self.path_is_reference(data_or_path):
                self._path = data_or_path
                self._sha256 = hashlib.sha256(data_or_path.encode("utf-8")).hexdigest()
                self._is_tmp = False
            else:
                self._set_file(data_or_path, is_tmp=False)
        else:
            if sample_rate is None:
                raise ValueError(
                    'Argument "sample_rate" is required when instantiating wandb.Audio with raw data.'
                )

            soundfile = util.get_module(
                "soundfile",
                required='Raw audio requires the soundfile package. To get it, run "pip install soundfile"',
            )

            tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + ".wav")

            soundfile.write(tmp_path, data_or_path, sample_rate)
            self._duration = len(data_or_path) / float(sample_rate)

            self._set_file(tmp_path, is_tmp=True)

    @classmethod
    def get_media_subdir(cls):
        """Get media subdirectory.

        <!-- lazydoc-ignore-classmethod: internal -->
        """
        return os.path.join("media", "audio")

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        """Deserialize JSON object into it's class representation.

        <!-- lazydoc-ignore-classmethod: internal -->
        """
        return cls(
            source_artifact.get_entry(json_obj["path"]).download(),
            caption=json_obj["caption"],
        )

    def bind_to_run(
        self, run, key, step, id_=None, ignore_copy_err: Optional[bool] = None
    ):
        """Bind this object to a run.

        <!-- lazydoc-ignore: internal -->
        """
        if self.path_is_reference(self._path):
            raise ValueError(
                "Audio media created by a reference to external storage cannot currently be added to a run"
            )

        return super().bind_to_run(run, key, step, id_, ignore_copy_err)

    def to_json(self, run):
        """Returns the JSON representation expected by the backend.

        <!-- lazydoc-ignore: internal -->
        """
        json_dict = super().to_json(run)
        json_dict.update(
            {
                "_type": self._log_type,
            }
        )
        return json_dict

    @classmethod
    def seq_to_json(cls, seq, run, key, step):
        """Convert a sequence of Audio objects to a JSON representation.

        <!-- lazydoc-ignore-classmethod: internal -->
        """
        audio_list = list(seq)

        util.get_module(
            "soundfile",
            required="wandb.Audio requires the soundfile package. To get it, run: pip install soundfile",
        )
        base_path = os.path.join(run.dir, "media", "audio")
        filesystem.mkdir_exists_ok(base_path)
        meta = {
            "_type": "audio",
            "count": len(audio_list),
            "audio": [a.to_json(run) for a in audio_list],
        }
        sample_rates = cls.sample_rates(audio_list)
        if sample_rates:
            meta["sampleRates"] = sample_rates
        durations = cls.durations(audio_list)
        if durations:
            meta["durations"] = durations
        captions = cls.captions(audio_list)
        if captions:
            meta["captions"] = captions

        return meta

    @classmethod
    def durations(cls, audio_list):
        """Calculate the duration of the audio files."""
        return [a._duration for a in audio_list]

    @classmethod
    def sample_rates(cls, audio_list):
        """Get sample rates of the audio files."""
        return [a._sample_rate for a in audio_list]

    @classmethod
    def captions(cls, audio_list):
        """Get the captions of the audio files.

        <!-- lazydoc-ignore-classmethod: internal -->
        """
        captions = [a._caption for a in audio_list]
        if all(c is None for c in captions):
            return False
        else:
            return ["" if c is None else c for c in captions]

    def resolve_ref(self):
        """Resolve the reference to the actual file path.

        <!-- lazydoc-ignore: internal -->
        """
        if self.path_is_reference(self._path):
            # this object was already created using a ref:
            return self._path
        source_artifact = self._artifact_source.artifact

        resolved_name = source_artifact._local_path_to_name(self._path)
        if resolved_name is not None:
            target_entry = source_artifact.manifest.get_entry_by_path(resolved_name)
            if target_entry is not None:
                return target_entry.ref

        return None

    def __eq__(self, other):
        if self.path_is_reference(self._path) or self.path_is_reference(other._path):
            # one or more of these objects is an unresolved reference -- we'll compare
            # their reference paths instead of their SHAs:
            return (
                self.resolve_ref() == other.resolve_ref()
                and self._caption == other._caption
            )

        return super().__eq__(other) and self._caption == other._caption

    def __ne__(self, other):
        return not self.__eq__(other)


class _AudioFileType(_dtypes.Type):
    name = "audio-file"
    types = [Audio]


_dtypes.TypeRegistry.add(_AudioFileType)
