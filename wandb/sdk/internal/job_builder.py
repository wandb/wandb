"""job builder."""
import json
import logging
import os
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.data_types._dtypes import TypeRegistry
from wandb.sdk.lib.filenames import DIFF_FNAME, METADATA_FNAME, REQUIREMENTS_FNAME
from wandb.util import make_artifact_name_safe

from .settings_static import SettingsStatic

if sys.version_info >= (3, 8):
    from typing import Literal, TypedDict
else:
    from typing_extensions import Literal, TypedDict

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import ArtifactRecord, UseArtifactRecord

FROZEN_REQUIREMENTS_FNAME = "requirements.frozen.txt"
JOB_FNAME = "wandb-job.json"
JOB_ARTIFACT_TYPE = "job"


class GitInfo(TypedDict):
    remote: str
    commit: str


class GitSourceDict(TypedDict):
    git: GitInfo
    entrypoint: List[str]
    notebook: bool


class ArtifactSourceDict(TypedDict):
    artifact: str
    entrypoint: List[str]
    notebook: bool


class ImageSourceDict(TypedDict):
    image: str


class JobSourceDict(TypedDict, total=False):
    _version: str
    source_type: str
    source: Union[GitSourceDict, ArtifactSourceDict, ImageSourceDict]
    input_types: Dict[str, Any]
    output_types: Dict[str, Any]
    runtime: Optional[str]
    _partial: Optional[str]  # flag to indicate incomplete job


class PartialJobSourceDict(TypedDict):
    job_name: str
    job_source_info: JobSourceDict


class ArtifactInfoForJob(TypedDict):
    id: str
    name: str


class JobArtifact(Artifact):
    def __init__(self, name: str, *args: Any, **kwargs: Any):
        super().__init__(name, "placeholder", *args, **kwargs)
        self._type = JOB_ARTIFACT_TYPE  # Get around type restriction.


class JobBuilder:
    _settings: SettingsStatic
    _metadatafile_path: Optional[str]
    _requirements_path: Optional[str]
    _config: Optional[Dict[str, Any]]
    _summary: Optional[Dict[str, Any]]
    _logged_code_artifact: Optional[ArtifactInfoForJob]
    _disable: bool
    _partial_source: Optional[PartialJobSourceDict]
    _aliases: List[str]
    _job_seq_id: Optional[str]
    _job_version_alias: Optional[str]

    def __init__(self, settings: SettingsStatic):
        self._settings = settings
        self._metadatafile_path = None
        self._requirements_path = None
        self._config = None
        self._summary = None
        self._logged_code_artifact = None
        self._job_seq_id = None
        self._job_version_alias = None
        self._disable = settings.disable_job_creation
        self._partial_source = None
        self._aliases = []
        self._source_type: Optional[
            Literal["repo", "artifact", "image"]
        ] = settings.job_source  # type: ignore[assignment]

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

    def _handle_server_artifact(
        self, res: Optional[Dict], artifact: "ArtifactRecord"
    ) -> None:
        if artifact.type == "job" and res is not None:
            try:
                if res["artifactSequence"]["latestArtifact"] is None:
                    self._job_version_alias = "v0"
                elif res["artifactSequence"]["latestArtifact"]["id"] == res["id"]:
                    self._job_version_alias = (
                        f"v{res['artifactSequence']['latestArtifact']['versionIndex']}"
                    )
                else:
                    self._job_version_alias = f"v{res['artifactSequence']['latestArtifact']['versionIndex'] + 1}"
                self._job_seq_id = res["artifactSequence"]["id"]
            except KeyError as e:
                _logger.info(f"Malformed response from ArtifactSaver.save {e}")
        if artifact.type == "code" and res is not None:
            self._logged_code_artifact = ArtifactInfoForJob(
                {
                    "id": res["id"],
                    "name": artifact.name,
                }
            )

    def _build_repo_job_source(
        self,
        metadata: Dict[str, Any],
        program_relpath: str,
        root: Optional[str],
    ) -> Tuple[Optional[GitSourceDict], Optional[str]]:
        git_info: Dict[str, str] = metadata.get("git", {})
        remote = git_info.get("remote")
        commit = git_info.get("commit")
        assert remote is not None
        assert commit is not None
        if self._is_notebook_run():
            if not os.path.exists(
                os.path.join(os.getcwd(), os.path.basename(program_relpath))
            ):
                return None, None

            if root is None or self._settings._jupyter_root is None:
                _logger.info("target path does not exist, exiting")
                return None, None
            assert self._settings._jupyter_root is not None
            # git notebooks set the root to the git root,
            # jupyter_root contains the path where the jupyter notebook was started
            # program_relpath contains the path from jupyter_root to the file
            # full program path here is actually the relpath from the program to the git root
            full_program_path = os.path.join(
                os.path.relpath(str(self._settings._jupyter_root), root),
                program_relpath,
            )
            full_program_path = os.path.normpath(full_program_path)
            # if the notebook server is started above the git repo need to clear all the ..s
            if full_program_path.startswith(".."):
                split_path = full_program_path.split("/")
                count_dots = 0
                for p in split_path:
                    if p == "..":
                        count_dots += 1
                full_program_path = "/".join(split_path[2 * count_dots :])

        else:
            full_program_path = program_relpath

        # TODO: update executable to a method that supports pex
        source: GitSourceDict = {
            "git": {
                "remote": remote,
                "commit": commit,
            },
            "entrypoint": [
                os.path.basename(sys.executable),
                full_program_path,
            ],
            "notebook": self._is_notebook_run(),
        }

        if self._settings.job_name:
            name = self._settings.job_name
        else:
            name = make_artifact_name_safe(f"job-{remote}_{program_relpath}")
        # if building a partial job from CLI, don't construct local entrypoint
        # or notebook flag entrypoint should already be in metadata from create_job
        if metadata.get("_partial"):
            assert "entrypoint" in metadata
            assert "notebook" in metadata
            source.update(
                {
                    "entrypoint": metadata["entrypoint"],
                    "notebook": metadata["notebook"],
                }
            )
        return source, name

    def _build_artifact_job_source(
        self, program_relpath: str
    ) -> Tuple[Optional[ArtifactSourceDict], Optional[str]]:
        assert isinstance(self._logged_code_artifact, dict)
        # TODO: should we just always exit early if the path doesn't exist?
        if self._is_notebook_run() and not self._is_colab_run():
            full_program_relpath = os.path.relpath(program_relpath, os.getcwd())
            # if the resolved path doesn't exist, then we shouldn't make a job because it will fail
            if not os.path.exists(full_program_relpath):
                # when users call log code in a notebook the code artifact starts
                # at the directory the notebook is in instead of the jupyter
                # core
                if os.path.exists(os.path.basename(program_relpath)):
                    full_program_relpath = os.path.basename(program_relpath)
                else:
                    _logger.info("target path does not exist, exiting")
                    return None, None
        else:
            full_program_relpath = program_relpath
        entrypoint = [
            os.path.basename(sys.executable),
            full_program_relpath,
        ]
        # TODO: update executable to a method that supports pex
        source: ArtifactSourceDict = {
            "entrypoint": entrypoint,
            "notebook": self._is_notebook_run(),
            "artifact": f"wandb-artifact://_id/{self._logged_code_artifact['id']}",
        }

        if self._settings.job_name:
            name = self._settings.job_name
        else:
            name = make_artifact_name_safe(f"job-{self._logged_code_artifact['name']}")

        return source, name

    def _build_image_job_source(
        self, metadata: Dict[str, Any]
    ) -> Tuple[ImageSourceDict, str]:
        image_name = metadata.get("docker")
        assert isinstance(image_name, str)

        raw_image_name = image_name
        if ":" in image_name:
            raw_image_name, tag = image_name.split(":")
            self._aliases += [tag]

        if self._settings.job_name:
            name = self._settings.job_name
        else:
            name = make_artifact_name_safe(f"job-{raw_image_name}")
        source: ImageSourceDict = {
            "image": image_name,
        }
        return source, name

    def _is_notebook_run(self) -> bool:
        return hasattr(self._settings, "_jupyter") and bool(self._settings._jupyter)

    def _is_colab_run(self) -> bool:
        return hasattr(self._settings, "_colab") and bool(self._settings._colab)

    def build(self) -> Optional[Artifact]:
        _logger.info("Attempting to build job artifact")
        if not os.path.exists(
            os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME)
        ):
            return None
        metadata = self._handle_metadata_file()
        if metadata is None:
            return None

        runtime: Optional[str] = metadata.get("python")
        program_relpath: Optional[str] = metadata.get("codePath")
        # can't build a job without a python version
        if runtime is None:
            return None

        if self._is_notebook_run():
            _logger.info("run is notebook based run")
            program_relpath = metadata.get("program")

        input_types = TypeRegistry.type_of(self._config).to_json()
        output_types = TypeRegistry.type_of(self._summary).to_json()

        name: Optional[str] = None
        source_info: Optional[JobSourceDict] = None

        if self._partial_source is not None:
            # construct source from downloaded partial job metadata
            name = self._partial_source["job_name"]
            source_info = self._partial_source["job_source_info"]
            # add input/output types now that we are actually running a run
            source_info.update(
                {"input_types": input_types, "output_types": output_types}
            )
            # set source_type to determine whether to add diff file to artifact
            source_type = source_info.get("source_type")
        else:
            # configure job from environment
            source_type = self._get_source_type(metadata, program_relpath)
            if not source_type:
                return None

            source: Union[
                Optional[GitSourceDict],
                Optional[ArtifactSourceDict],
                Optional[ImageSourceDict],
            ] = None

            # make source dict
            if source_type == "repo":
                assert program_relpath is not None
                source, name = self._build_repo_job_source(
                    metadata,
                    program_relpath,
                    metadata.get("root"),
                )
            elif source_type == "artifact":
                assert program_relpath is not None
                source, name = self._build_artifact_job_source(program_relpath)
            elif source_type == "image":
                source, name = self._build_image_job_source(metadata)
            else:
                source = None

            if source is None:
                return None

            source_info = {
                "_version": "v0",
                "source_type": source_type,
                "source": source,
                "input_types": input_types,
                "output_types": output_types,
                "runtime": runtime,
            }

        assert source_info is not None
        assert name is not None
        if metadata.get("_partial"):
            assert not self._partial_source, "partial job has partial output"
            source_info.update({"_partial": metadata["_partial"]})

        artifact = JobArtifact(name)

        _logger.info("adding wandb-job metadata file")
        with artifact.new_file("wandb-job.json") as f:
            f.write(json.dumps(source_info, indent=4))

        artifact.add_file(
            os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME),
            name=FROZEN_REQUIREMENTS_FNAME,
        )

        if source_type == "repo":
            # add diff
            if os.path.exists(os.path.join(self._settings.files_dir, DIFF_FNAME)):
                artifact.add_file(
                    os.path.join(self._settings.files_dir, DIFF_FNAME),
                    name=DIFF_FNAME,
                )

        return artifact

    def _get_source_type(
        self, metadata: Dict[str, Any], relpath: Optional[str]
    ) -> Optional[str]:
        if self._source_type:
            return self._source_type

        if self._has_git_job_ingredients(metadata, relpath):
            _logger.info("is repo sourced job")
            return "repo"

        if self._has_artifact_job_ingredients(relpath):
            _logger.info("is artifact sourced job")
            return "artifact"

        if self._has_image_job_ingredients(metadata):
            _logger.info("is image sourced job")
            return "image"

        _logger.info("no source found")
        return None

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
        if program_relpath is None:
            return False
        if self._is_notebook_run() and metadata.get("root") is None:
            return False
        return git_info.get("remote") is not None and git_info.get("commit") is not None

    def _has_artifact_job_ingredients(self, program_relpath: Optional[str]) -> bool:
        return self._logged_code_artifact is not None and program_relpath is not None

    def _has_image_job_ingredients(self, metadata: Dict[str, Any]) -> bool:
        return metadata.get("docker") is not None


def convert_use_artifact_to_job_source(
    use_artifact: "UseArtifactRecord",
) -> PartialJobSourceDict:
    source_info = use_artifact.partial.source_info
    source_info_dict: JobSourceDict = {
        "_version": "v0",
        "source_type": source_info.source_type,
        "runtime": source_info.runtime,
    }
    if source_info.source_type == "repo":
        entrypoint = [str(x) for x in source_info.source.git.entrypoint]
        git_source: GitSourceDict = {
            "git": {
                "remote": source_info.source.git.git_info.remote,
                "commit": source_info.source.git.git_info.commit,
            },
            "entrypoint": entrypoint,
            "notebook": source_info.source.git.notebook,
        }
        source_info_dict.update({"source": git_source})
    elif source_info.source_type == "artifact":
        entrypoint = [str(x) for x in source_info.source.artifact.entrypoint]
        artifact_source: ArtifactSourceDict = {
            "artifact": source_info.source.artifact.artifact,
            "entrypoint": entrypoint,
            "notebook": source_info.source.artifact.notebook,
        }
        source_info_dict.update({"source": artifact_source})
    elif source_info.source_type == "image":
        image_source: ImageSourceDict = {
            "image": source_info.source.image.image,
        }
        source_info_dict.update({"source": image_source})

    partal_job_source_dict: PartialJobSourceDict = {
        "job_name": use_artifact.partial.job_name.split(":")[0],
        "job_source_info": source_info_dict,
    }
    return partal_job_source_dict
