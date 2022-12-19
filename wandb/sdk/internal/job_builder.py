"""
job builder.
"""
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from wandb.sdk.lib.filenames import DIFF_FNAME, METADATA_FNAME, REQUIREMENTS_FNAME
from wandb.util import make_artifact_name_safe
from wandb.sdk.wandb_config import Config
from wandb.sdk.wandb_summary import Summary
from wandb.sdk.wandb_artifacts import Artifact
from wandb.sdk.data_types._dtypes import TypeRegistry
from .settings_static import SettingsStatic

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

FROZEN_REQUIREMENTS_FNAME = "requirements.frozen.txt"
JOB_FNAME = "wandb-job.json"
JOB_ARTIFACT_TYPE = "job"


class GitSourceDict(TypedDict):
    remote: str
    commit: str
    entrypoint: List[str]
    args: Sequence[str]


class ArtifactSourceDict(TypedDict):
    artifact: str
    entrypoint: List[str]
    args: Sequence[str]


class ImageSourceDict(TypedDict):
    image: str
    args: Sequence[str]


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
    _logged_code_artifact: Optional[ArtifactInfoForJob]

    def __init__(self, settings: SettingsStatic):
        self._settings = settings
        self._metadatafile_path = None
        self._requirements_path = None
        self._config = None
        self._summary = None
        self._logged_code_artifact = None
        self.used_job = False

    def _set_config(self, config: Config):
        self._config = config

    def _set_summary(self, summary: Summary):
        self._summary = summary

    def create_input_types(self, config: Config):
        raise NotImplementedError

    def create_output_types(self, summary: Summary):
        raise NotImplementedError

    def _build_repo_job(
        self, remote: str, commit: str
    ) -> Tuple[Artifact, GitSourceDict]:
        source: GitSourceDict = {
            "entrypoint": [
                sys.executable.split("/")[-1],
                self.program_relpath,
            ],
            "args": self.args,
            "remote": remote,
            "commit": commit,
        }

        name = make_artifact_name_safe(f"job-{remote}-{self.program_relpath}")

        artifact = Artifact(name, JOB_ARTIFACT_TYPE)
        if os.path.exists(os.path.join(self._settings.files_dir, DIFF_FNAME)):
            artifact.add_file(
                os.path.join(self._settings.files_dir, DIFF_FNAME),
                name="diff.patch",
            )
        return artifact, source

    def _build_artifact_job(self) -> Tuple[Artifact, ArtifactSourceDict]:
        source: ArtifactSourceDict = {
            "entrypoint": [
                sys.executable.split("/")[-1],
                self.program_relpath,
            ],
            "args": self.args,
            "artifact": f"wandb-artifact://_id/{self._logged_code_artifact['id']}",
        }

        name = f"job-{self._logged_code_artifact['name']}-{self.program_relpath}"

        artifact = Artifact(name, JOB_ARTIFACT_TYPE)
        return artifact, source

    def _build_image_job(self) -> Tuple[Artifact, ImageSourceDict]:
        name = make_artifact_name_safe(f"job-{self._settings.docker}")
        artifact = Artifact(name, JOB_ARTIFACT_TYPE)
        source: ImageSourceDict = {
            "image": self._settings.docker,
            "args": self.args,
        }
        return artifact, source

    def _build(self) -> Optional[Artifact]:
        artifact = None
        if not os.path.exists(
            os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME)
        ):
            return None
        metadata = {}
        # TODO: settings static is not populated with several
        # fields that are in settings in offline mode. Instead
        # use metadata file to pull these fields.
        if os.path.exists(os.path.join(self._settings.files_dir, METADATA_FNAME)):
            with open(os.path.join(self._settings.files_dir, METADATA_FNAME), "r") as f:
                metadata = json.load(f)
        else:
            return None

        source_type = None
        git_info = metadata.get("git", {})
        docker = metadata.get("docker", None)
        self.program_relpath = metadata.get("codePath", None)
        self.args = metadata.get("args", [])
        if git_info.get("remote") is not None and git_info.get("commit") is not None:
            artifact, source = self._build_repo_job(
                git_info.get("remote"), git_info.get("commit")
            )
            source_type = "git"
        elif self._logged_code_artifact is not None:
            artifact, source = self._build_artifact_job()
            source_type = "artifact"
        elif docker is not None:
            artifact, source = self._build_image_job()
            source_type = "image"

        # need an entrypoint for git and artifact jobs
        if source_type in ["git", "artifact"] and self.program_relpath is None:
            return None

        input_types = TypeRegistry.type_of(self._config).to_json()
        output_types = TypeRegistry.type_of(self._summary).to_json()

        source_info: JobSourceDict = {
            "_version": "v0",
            "source_type": source_type,
            "source": source,
            "input_types": input_types,
            "output_types": output_types,
            "runtime": metadata.get("python", None),
        }

        with artifact.new_file("wandb-job.json") as f:
            f.write(json.dumps(source_info, indent=4))

        artifact.add_file(
            os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME),
            name=FROZEN_REQUIREMENTS_FNAME,
        )

        return artifact
