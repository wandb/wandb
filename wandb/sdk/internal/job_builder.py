"""job builder."""
import json
import os
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from wandb.sdk.data_types._dtypes import TypeRegistry
from wandb.sdk.lib.filenames import DIFF_FNAME, METADATA_FNAME, REQUIREMENTS_FNAME
from wandb.sdk.wandb_artifacts import Artifact
from wandb.util import make_artifact_name_safe

from .settings_static import SettingsStatic

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import ArtifactRecord

FROZEN_REQUIREMENTS_FNAME = "requirements.frozen.txt"
JOB_FNAME = "wandb-job.json"
JOB_ARTIFACT_TYPE = "job"


class GitInfo(TypedDict):
    remote: str
    commit: str


class GitSourceDict(TypedDict):
    git: GitInfo
    entrypoint: List[str]


class ArtifactSourceDict(TypedDict):
    artifact: str
    entrypoint: List[str]


class ImageSourceDict(TypedDict):
    image: str


class JobSourceDict(TypedDict, total=False):
    _version: str
    source_type: str
    source: Union[GitSourceDict, ArtifactSourceDict, ImageSourceDict]
    input_types: Dict[str, Any]
    output_types: Dict[str, Any]
    runtime: Optional[str]


class ArtifactInfoForJob(TypedDict):
    id: str
    name: str


class JobBuilder:
    _settings: SettingsStatic
    _metadatafile_path: Optional[str]
    _requirements_path: Optional[str]
    _config: Optional[Dict[str, Any]]
    _summary: Optional[Dict[str, Any]]
    _logged_code_artifact: Optional[ArtifactInfoForJob]
    _disable: bool

    def __init__(self, settings: SettingsStatic):
        self._settings = settings
        self._metadatafile_path = None
        self._requirements_path = None
        self._config = None
        self._summary = None
        self._logged_code_artifact = None
        self._disable = settings.disable_job_creation

    def set_config(self, config: Dict[str, Any]) -> None:
        self._config = config

    def set_summary(self, summary: Dict[str, Any]) -> None:
        self._summary = summary

    @property
    def disable(self) -> bool:
        return self._disable

    @disable.setter
    def disable(self, val: bool) -> None:
        self._disable = val

    def _set_logged_code_artifact(
        self, res: Optional[Dict], artifact: "ArtifactRecord"
    ) -> None:
        if artifact.type == "code" and res is not None:
            self._logged_code_artifact = ArtifactInfoForJob(
                {
                    "id": res["id"],
                    "name": artifact.name,
                }
            )

    def _build_repo_job(
        self, metadata: Dict[str, Any], program_relpath: str
    ) -> Tuple[Artifact, GitSourceDict]:
        git_info: Dict[str, str] = metadata.get("git", {})
        remote = git_info.get("remote")
        commit = git_info.get("commit")
        assert remote is not None
        assert commit is not None
        # TODO: update executable to a method that supports pex
        source: GitSourceDict = {
            "entrypoint": [
                os.path.basename(sys.executable),
                program_relpath,
            ],
            "git": {
                "remote": remote,
                "commit": commit,
            },
        }

        name = make_artifact_name_safe(f"job-{remote}_{program_relpath}")

        artifact = Artifact(name, JOB_ARTIFACT_TYPE)
        if os.path.exists(os.path.join(self._settings.files_dir, DIFF_FNAME)):
            artifact.add_file(
                os.path.join(self._settings.files_dir, DIFF_FNAME),
                name="diff.patch",
            )
        return artifact, source

    def _build_artifact_job(
        self, program_relpath: str
    ) -> Tuple[Artifact, ArtifactSourceDict]:
        assert isinstance(self._logged_code_artifact, dict)
        # TODO: update executable to a method that supports pex
        source: ArtifactSourceDict = {
            "entrypoint": [
                os.path.basename(sys.executable),
                program_relpath,
            ],
            "artifact": f"wandb-artifact://_id/{self._logged_code_artifact['id']}",
        }
        name = make_artifact_name_safe(f"job-{self._logged_code_artifact['name']}")

        artifact = Artifact(name, JOB_ARTIFACT_TYPE)
        return artifact, source

    def _build_image_job(
        self, metadata: Dict[str, Any]
    ) -> Tuple[Artifact, ImageSourceDict]:
        image_name = metadata.get("docker")
        assert isinstance(image_name, str)
        name = make_artifact_name_safe(f"job-{image_name}")
        artifact = Artifact(name, JOB_ARTIFACT_TYPE)
        source: ImageSourceDict = {
            "image": image_name,
        }
        return artifact, source

    def build(self) -> Optional[Artifact]:
        if not os.path.exists(
            os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME)
        ):
            return None
        metadata = self._handle_metadata_file()
        if metadata is None:
            return None

        runtime: Optional[str] = metadata.get("python")
        # can't build a job without a python version
        if runtime is None:
            return None

        program_relpath: Optional[str] = metadata.get("codePath")

        artifact = None
        source_type = None
        source: Optional[
            Union[GitSourceDict, ArtifactSourceDict, ImageSourceDict]
        ] = None

        if self._has_git_job_ingredients(metadata, program_relpath):
            assert program_relpath is not None
            artifact, source = self._build_repo_job(metadata, program_relpath)
            source_type = "repo"
        elif self._has_artifact_job_ingredients(program_relpath):
            assert program_relpath is not None
            artifact, source = self._build_artifact_job(program_relpath)
            source_type = "artifact"
        elif self._has_image_job_ingredients(metadata):
            artifact, source = self._build_image_job(metadata)
            source_type = "image"

        if artifact is None or source_type is None or source is None:
            return None

        input_types = TypeRegistry.type_of(self._config).to_json()
        output_types = TypeRegistry.type_of(self._summary).to_json()

        source_info: JobSourceDict = {
            "_version": "v0",
            "source_type": source_type,
            "source": source,
            "input_types": input_types,
            "output_types": output_types,
            "runtime": runtime,
        }

        with artifact.new_file("wandb-job.json") as f:
            f.write(json.dumps(source_info, indent=4))

        artifact.add_file(
            os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME),
            name=FROZEN_REQUIREMENTS_FNAME,
        )

        return artifact

    def _handle_metadata_file(
        self,
    ) -> Optional[Dict]:
        if os.path.exists(os.path.join(self._settings.files_dir, METADATA_FNAME)):
            with open(os.path.join(self._settings.files_dir, METADATA_FNAME)) as f:
                metadata: Dict = json.load(f)
            return metadata

        return None

    def _has_git_job_ingredients(
        self, metadata: Dict[str, Any], program_relpath: Optional[str]
    ) -> bool:
        git_info: Dict[str, str] = metadata.get("git", {})
        return (
            git_info.get("remote") is not None
            and git_info.get("commit") is not None
            and program_relpath is not None
        )

    def _has_artifact_job_ingredients(self, program_relpath: Optional[str]) -> bool:
        return self._logged_code_artifact is not None and program_relpath is not None

    def _has_image_job_ingredients(self, metadata: Dict[str, Any]) -> bool:
        return metadata.get("docker") is not None
