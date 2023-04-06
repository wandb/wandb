import glob
import hashlib
import pathlib
import shutil
import tempfile
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    Iterable,
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
        self._source_path: Optional[pathlib.Path] = None
        self._is_temp_path: bool = False
        self._bind_path: Optional[pathlib.Path] = None
        self._artifact: Optional[ArtifactReference] = None
        self._size: Optional[int] = None
        self._sha256: Optional[str] = None

    def to_json(self) -> dict:
        """Serialize this media object to JSON.

        Returns:
            dict: A JSON representation of this media object.
        """
        serialized = {
            "_type": self.OBJ_TYPE,
        }
        if self._size:
            serialized.update({"size": self._size})
        if self._sha256:
            serialized["sha256"] = self._sha256
        if self._bind_path:
            serialized["path"] = str(self._bind_path)

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
            if self._is_temp_path:
                path = self.RELATIVE_PATH / self._source_path.name
            else:
                assert self._sha256 is not None
                path = self.RELATIVE_PATH / self._sha256[:20] / self._source_path.name
            entry = artifact.add_file(
                str(self._source_path), str(path), is_tmp=self._is_temp_path
            )
            path = entry.path
        # self._bind_path = pathlib.Path(path)
        return {
            "path": path,
            "sha256": self._sha256,
            "_type": self.OBJ_ARTIFACT_TYPE,
        }

    def bind_to_run(
        self,
        run: "Run",
        *namespace: Iterable[str],
        suffix: str = "",
    ) -> None:
        """Bind this media object to a run.

        Args:
            interface: The interface to the run.
            start: The path to the run directory.
            namespace: A list of path components to prefix to the media path.
            suffix: A suffix to append to the media path.
        """
        sep = self.FILE_SEP
        file_name = pathlib.Path(sep.join(namespace)).with_suffix(suffix)  # type: ignore

        root_dir = pathlib.Path(run.dir)

        dest_path = root_dir / self.RELATIVE_PATH / file_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if self._is_temp_path:
            shutil.move(str(self._source_path), dest_path)
        else:
            shutil.copy(self._source_path, dest_path)

        self._source_path = dest_path
        self._is_temp_path = False
        self._bind_path = dest_path.relative_to(root_dir)
        files = {"files": [(glob.escape(str(self._bind_path)), "now")]}
        assert run._backend and run._backend.interface
        run._backend.interface.publish_files(files)  # type: ignore

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
        self._items = [item_type(item) for item in items]

    def bind_to_run(
        self,
        interface,
        root_dir: pathlib.Path,
        *namespace: Sequence[str],
    ) -> None:
        for i, item in enumerate(self._items):
            item.bind_to_run(interface, root_dir, *namespace, str(i))  # type: ignore

    def to_json(self) -> dict:
        ...
