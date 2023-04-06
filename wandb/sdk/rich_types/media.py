import glob
import hashlib
import os
import pathlib
import shutil
import tempfile
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
)

from wandb import util

if TYPE_CHECKING:
    from wandb.sdk.wandb_artifacts import Artifact
    from wandb.sdk.wandb_run import Run

MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")


T = TypeVar("T")
U = TypeVar("U")


class ArtifactReference:
    def __init__(self, artifact: "Artifact", path: str) -> None:
        self._artifact = artifact
        self._path = path

    @property
    def artifact_path(self) -> str:
        return f"wandb-client-artifact://{self._artifact._client_id}/{str(self._path)}"

    @property
    def artifact_path_latest(self) -> str:
        return f"wandb-client-artifact://{self._artifact._sequence_client_id}:latest/{str(self._path)}"


class Media:
    RELATIVE_PATH = pathlib.Path("media")
    FILE_SEP = "_"
    OBJ_TYPE = "file"
    OBJ_ARTIFACT_TYPE = "file"

    def __init__(self) -> None:
        self._source_path: Optional[Union[str, os.PathLike]] = None
        self._is_temp_path: bool = False
        self._size: Optional[int] = None
        self._sha256: Optional[str] = None

        self._bind_path: Optional[pathlib.Path] = None
        self._artifact: Optional[ArtifactReference] = None

    def to_json(self) -> Dict[str, Any]:
        """Serialize this media object to JSON.

        Returns:
            A JSON-serializable dictionary.
        """
        serialized = {
            "_type": self.OBJ_TYPE,
            "path": str(self._bind_path),
            "size": self._size,
            "sha256": self._sha256,
        }

        if self._artifact:
            serialized["artifact_path"] = self._artifact.artifact_path
            serialized["_latest_artifact_path"] = self._artifact.artifact_path_latest

        return serialized

    def bind_to_artifact(self, artifact: "Artifact") -> Dict[str, Any]:
        """Bind this media object to an artifact.

        Args:
            artifact (Artifact): The artifact to bind to.
        """
        if self._source_path is None:
            return {"_type": self.OBJ_ARTIFACT_TYPE}

        path = artifact.get_added_local_path_name(str(self._source_path))
        if path is None:
            file_name = pathlib.Path(self._source_path).name
            if self._is_temp_path:
                path = self.RELATIVE_PATH / file_name
            else:
                assert self._sha256 is not None
                path = self.RELATIVE_PATH / self._sha256[:20] / file_name
            entry = artifact.add_file(
                str(self._source_path), str(path), is_tmp=self._is_temp_path
            )
            path = entry.path
        self._bind_path = pathlib.Path(path)

        return {
            "_type": self.OBJ_ARTIFACT_TYPE,
            "path": str(self._bind_path),
            "sha256": self._sha256,
        }

    def bind_to_run(
        self,
        run: "Run",
        *namespace: str,
        suffix: str = "",
    ) -> None:
        """Bind this media object to a run.

        Args:
            run (Run): The run to bind to.
            namespace (Iterable[str]): The namespace to bind to.
            suffix: A suffix to append to the media path.
        """
        root_dir = pathlib.Path(run.dir)
        dest_path = self._generate_media_path(root_dir, *namespace, suffix=suffix)

        if self._is_temp_path:
            shutil.move(str(self._source_path), dest_path)
        else:
            shutil.copy(str(self._source_path), dest_path)

        self._source_path = dest_path
        self._is_temp_path = False
        self._bind_path = pathlib.Path(dest_path).relative_to(root_dir)

        self._publish(run, self._bind_path)

    def _save_file_metadata(
        self, path: Union[str, os.PathLike], is_temp: bool = False
    ) -> None:
        """Save the metadata for this media object.

        Args:
            path (os.PathLike): The path to the media.
        """
        self._source_path = pathlib.Path(path).absolute()
        self._is_temp_path = is_temp
        self._size = self._source_path.stat().st_size
        self._sha256 = self._compute_sha256(self._source_path)

    @staticmethod
    def _publish(run: "Run", path: os.PathLike) -> None:
        """Publish this media object to the run.

        Args:
            run (Run): The run to publish to.
            path (os.PathLike): The path to the media.
        """
        assert run._backend and run._backend.interface
        assert path is not None

        interface = run._backend.interface

        files = {"files": [(glob.escape(str(path)), "now")]}
        interface.publish_files(files)  # type: ignore

    def _generate_media_path(
        self, root_dir: os.PathLike, *namespace: str, suffix: str = ""
    ) -> os.PathLike:
        """Generate a media path for this media object.

        Args:
            root_dir (os.PathLike): The root directory to generate the path in.
            namespace (Iterable[str]): The namespace to generate the path in.
            suffix (str, optional): The suffix for this media object's path. Defaults to "".

        Returns:
            pathlib.Path: The media path for this media object.
        """
        sep = self.FILE_SEP
        file_name = pathlib.Path(sep.join(namespace)).with_suffix(suffix)

        path = pathlib.Path(root_dir) / self.RELATIVE_PATH / file_name
        path.parent.mkdir(parents=True, exist_ok=True)

        return path

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


class MediaSequenceFactory(Generic[T, U]):
    _registry = {}

    @classmethod
    def register(cls, source_cls: Type[T], target_cls: Type[U]) -> None:
        cls._registry[source_cls] = target_cls

    @classmethod
    def create(cls, sequence: Sequence[T]) -> Union[U, Sequence[T]]:
        # TODO: handle case where sequence is not list-like
        target_cls = cls._registry.get(type(sequence[0]))
        if target_cls:
            return target_cls(sequence)
        # TODO: handle case where type is not registered
        return sequence


def register(source_cls: Type[T]) -> Callable:
    def decorator(target_cls: Type[U]):
        MediaSequenceFactory.register(source_cls, target_cls)
        return target_cls

    return decorator


class MediaSequence(Generic[T, U]):
    def __init__(self, items: Sequence[T], item_type: Type[U]):
        self._items = [item for item in items]

    def bind_to_run(
        self,
        run,
        root_dir: pathlib.Path,
        *namespace: Sequence[str],
    ) -> None:
        for i, item in enumerate(self._items):
            item.bind_to_run(run, root_dir, *namespace, str(i))  # type: ignore

    def bind_to_artifact(self, artifact: "Artifact") -> Any:
        for item in self._items:
            item.bind_to_artifact(artifact)  # type: ignore

    def to_json(self) -> dict:
        ...
