import pathlib
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Union

from .media import Media, MediaSequence, register

if TYPE_CHECKING:
    from wandb.sdk.wandb_artifacts import Artifact
    from wandb.sdk.wandb_run import Run


class Audio(Media):
    OBJ_TYPE = "audio-file"
    OBJ_ARTIFACT_TYPE = "audio-file"
    RELATIVE_PATH = pathlib.Path("media") / "audio"
    DEFAULT_FORMAT = "WAV"

    _format: str

    def __init__(
        self,
        data_or_path,
        sample_rate: Optional[int] = None,
        caption: Optional[str] = None,
    ) -> None:
        super().__init__()
        if isinstance(data_or_path, (str, pathlib.Path)):
            self.from_path(data_or_path)
        elif isinstance(data_or_path, Audio):
            self.from_audio(data_or_path)
        else:
            self.from_array(data_or_path, sample_rate=sample_rate)

        self._caption = caption

    def from_audio(self, audio: "Audio") -> None:
        excluded = set()
        for k, v in audio.__dict__.items():
            if k not in excluded:
                setattr(self, k, v)

    def from_path(self, path: Union[str, pathlib.Path]) -> None:
        with self.manager.save(path) as source_path:
            self._format = (source_path.suffix[1:] or self.DEFAULT_FORMAT).lower()

    def from_array(
        self,
        data,
        sample_rate: Optional[int] = None,
    ) -> None:
        assert sample_rate is not None, "sample_rate must be specified"

        import soundfile as sf

        self._format = self.DEFAULT_FORMAT.lower()
        with self.manager.save(suffix=f".{self._format}") as source_path:
            sf.write(source_path, data, sample_rate)

    def bind_to_run(self, run: "Run", *namespace, name: Optional[str] = None) -> None:
        """Bind this audio object to a run.

        Args:
            run: The run to bind to.
            namespace: The namespace to use.
            name: The name of the audio object.
        """
        return super().bind_to_run(
            run,
            *namespace,
            name=name,
            suffix=f".{self._format}",
        )

    def bind_to_artifact(
        self,
        artifact: "Artifact",
    ) -> dict:
        serialized = super().bind_to_artifact(artifact)
        serialized.update({"format": self._format})
        return serialized

    def to_json(self) -> dict:
        serialized = super().to_json()
        if self._caption:
            serialized["caption"] = self._caption
        return serialized


@register(Audio)
class AudioSequence(MediaSequence[Any, Audio]):
    OBJ_TYPE = "audio"
    OBJ_ARTIFACT_TYPE = "audio"

    def __init__(self, items: Sequence[Any]):
        super().__init__(items, Audio)

    def bind_to_artifact(self, artifact: "Artifact") -> Dict[str, Any]:
        super().bind_to_artifact(artifact)
        return {
            "_type": self.OBJ_ARTIFACT_TYPE,
        }

    def to_json(self) -> dict:
        items = [item.to_json() for item in self._items]
        return {
            "_type": self.OBJ_TYPE,
            "count": len(items),
            "audio": items,
        }
