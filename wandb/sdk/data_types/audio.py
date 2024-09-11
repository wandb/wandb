import hashlib
import os
from typing import Optional

from wandb import util
from wandb.sdk.lib import filesystem, runid

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.media import BatchableMedia


class Audio(BatchableMedia):
    """Wandb class for audio clips.

    Arguments:
        data_or_path: (string or numpy array) A path to an audio file
            or a numpy array of audio data.
        sample_rate: (int) Sample rate, required when passing in raw
            numpy array of audio data.
        caption: (string) Caption to display with audio.
    """

    _log_type = "audio-file"

    def __init__(self, data_or_path, sample_rate=None, caption=None):
        """Accept a path to an audio file or a numpy array of audio data."""
        super().__init__()
        self._duration = None
        self._sample_rate = sample_rate
        self._caption = caption

        if isinstance(data_or_path, str):
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
        return os.path.join("media", "audio")

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        return cls(
            source_artifact.get_entry(json_obj["path"]).download(),
            caption=json_obj["caption"],
        )

    def bind_to_run(
        self, run, key, step, id_=None, ignore_copy_err: Optional[bool] = None
    ):
        if self.path_is_reference(self._path):
            raise ValueError(
                "Audio media created by a reference to external storage cannot currently be added to a run"
            )

        return super().bind_to_run(run, key, step, id_, ignore_copy_err)

    def to_json(self, run):
        json_dict = super().to_json(run)
        json_dict.update(
            {
                "_type": self._log_type,
                "caption": self._caption,
            }
        )
        return json_dict

    @classmethod
    def seq_to_json(cls, seq, run, key, step):
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
        return [a._duration for a in audio_list]

    @classmethod
    def sample_rates(cls, audio_list):
        return [a._sample_rate for a in audio_list]

    @classmethod
    def captions(cls, audio_list):
        captions = [a._caption for a in audio_list]
        if all(c is None for c in captions):
            return False
        else:
            return ["" if c is None else c for c in captions]

    def resolve_ref(self):
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
