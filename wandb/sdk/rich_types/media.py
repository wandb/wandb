import glob
import hashlib
import os
import pathlib
import shutil
import tempfile
from contextlib import contextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generator,
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


T = TypeVar("T")
U = TypeVar("U")


class MediaArtifactManager:
    def __init__(self) -> None:
        self._artifact: Optional["Artifact"] = None
        self._path: Optional[str] = None

    def assign(self, artifact: "Artifact", path: str) -> Any:
        if self._artifact is not None or self._path is not None:
            raise ValueError(
                f"Media object already has an artifact ({self.pprint()}) set."
            )
        self._artifact = artifact
        self._path = path

    @property
    def artifact_path(self) -> Optional[str]:
        if self._artifact is None or self._path is None:
            return None
        if self._artifact._client_id is None or not self._artifact._final:
            return None
        return f"wandb-client-artifact://{self._artifact._client_id}/{str(self._path)}"

    @property
    def artifact_path_latest(self) -> Optional[str]:
        if self._artifact is None or self._path is None:
            return None
        if self._artifact._client_id is None or not self._artifact._final:
            return None
        return f"wandb-client-artifact://{self._artifact._sequence_client_id}:latest/{str(self._path)}"

    def pprint(self) -> str:
        return f"{self._artifact}/{self._path}"

    def to_json(self) -> Dict[str, Any]:
        if self.artifact_path is None or self.artifact_path_latest is None:
            return {}
        return {
            "artifact_path": self.artifact_path,
            "_latest_artifact_path": self.artifact_path_latest,
        }


class MediaPathManager:
    FILE_SEP = "_"
    MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")

    def __init__(self, relative_path: Union[str, os.PathLike]) -> None:
        self._relative_path: pathlib.Path = pathlib.Path(relative_path)

        self._source_path: Optional[Union[str, os.PathLike]] = None
        self._is_temp_path: bool = False
        self._size: Optional[int] = None
        self._sha256: Optional[str] = None

        self._bind_path: Optional[Union[str, os.PathLike]] = None

    def run_to_json(self) -> Dict[str, Any]:
        return {
            "path": str(self._bind_path),
            "size": self._size,
            "sha256": self._sha256,
        }

    def artifact_to_json(self) -> Dict[str, Any]:
        if self._source_path:
            return {
                "path": str(self._bind_path),
                "sha256": self._sha256,
            }
        return {}

    @contextmanager
    def save(
        self, path: Optional[Union[str, os.PathLike]] = None, suffix: str = ""
    ) -> Generator[pathlib.Path, None, None]:
        """Save the metadata for this media object.

        Args:
            path (os.PathLike): The path to the media.
            suffix (str): The suffix to append to the media path.

        Returns:
            pathlib.Path: The path to the media.
        """
        try:
            if path is None:
                self._is_temp_path = True
                path = self.get_temp_path(suffix=suffix)
            self._source_path = pathlib.Path(path).absolute()
            yield self._source_path
        finally:
            assert isinstance(self._source_path, pathlib.Path)
            self._size = self._source_path.stat().st_size
            self._sha256 = self._compute_sha256(self._source_path)

    def bind_to_run(self, root_dir, *namespace, suffix) -> None:
        # construct destination path in the root_dir
        sep = self.FILE_SEP
        file_name = pathlib.Path(sep.join(namespace)).with_suffix(suffix)

        dest_path = pathlib.Path(root_dir) / self._relative_path / file_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if self._is_temp_path:
            shutil.move(str(self._source_path), dest_path)
        else:
            shutil.copy(str(self._source_path), dest_path)

        self._source_path = dest_path
        self._is_temp_path = False
        self._bind_path = pathlib.Path(dest_path).relative_to(root_dir)

    def bind_to_artifact(self, artifact: "Artifact") -> None:
        """Bind this media object to an artifact.

        Args:
            artifact: The artifact to bind to.
        """
        if self._source_path is None:
            return

        path = artifact.get_added_local_path_name(str(self._source_path))
        if path is None:
            file_name = pathlib.Path(self._source_path).name
            if self._is_temp_path:
                path = self._relative_path / file_name
            else:
                assert self._sha256 is not None
                path = self._relative_path / self._sha256[:20] / file_name
            entry = artifact.add_file(
                str(self._source_path), str(path), is_tmp=self._is_temp_path
            )
            path = entry.path
        self._bind_path = pathlib.Path(path)

    def get_temp_path(self, suffix: str = "") -> pathlib.Path:
        """Get a temporary path for a media object.

        Args:
            suffix (str, optional): The suffix for this media object's path. Defaults to "".

        Returns:
            pathlib.Path: The temporary path for this media.
        """
        return self.MEDIA_TMP.name / pathlib.Path(util.generate_id()).with_suffix(
            suffix
        )

    @staticmethod
    def _compute_sha256(file: Union[str, os.PathLike]) -> str:
        """Get the sha256 hash for this media.

        Args:
            file (pathlib.Path): The path to the media.

        Returns:
            str: The sha256 hash for this media.
        """
        with open(file, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        return file_hash


class Media:
    RELATIVE_PATH = pathlib.Path("media")
    OBJ_TYPE = "file"
    OBJ_ARTIFACT_TYPE = "file"

    def __init__(self) -> None:
        self._path = MediaPathManager(self.RELATIVE_PATH)
        self._artifact = MediaArtifactManager()

    @property
    def path(self) -> MediaPathManager:
        return self._path

    @property
    def artifact(self) -> MediaArtifactManager:
        return self._artifact

    def to_json(self) -> Dict[str, Any]:
        """Serialize this media object to JSON.

        Returns:
            A JSON-serializable dictionary.
        """
        return {
            "_type": self.OBJ_TYPE,
            **self._path.run_to_json(),
            **self._artifact.to_json(),
        }

    def bind_to_artifact(self, artifact: "Artifact") -> Dict[str, Any]:
        """Bind this media object to an artifact.

        Args:
            artifact (Artifact): The artifact to bind to.
        """
        self._path.bind_to_artifact(artifact)
        return {
            "_type": self.OBJ_ARTIFACT_TYPE,
            **self._path.artifact_to_json(),
        }

    def bind_to_run(
        self, run: "Run", *namespace: str, name: Optional[str] = None, suffix: str = ""
    ) -> None:
        """Bind this media object to a run.

        Args:
            run (Run): The run to bind to.
            namespace (Iterable[str]): The namespace to bind to.
            suffix (str): The suffix to use.
        """
        assert self._path._sha256 is not None
        name = name or self._path._sha256[:20]
        self._path.bind_to_run(run.dir, *namespace, name, suffix=suffix)

        path = self._path._bind_path
        assert path is not None

        assert run._backend and run._backend.interface
        interface = run._backend.interface

        files = {"files": [(glob.escape(str(path)), "now")]}
        interface.publish_files(files)  # type: ignore


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
