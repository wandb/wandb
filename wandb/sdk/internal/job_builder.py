"""job builder."""

import json
import logging
import os
import re
import sys
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    TypedDict,
    Union,
)

import wandb
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.data_types._dtypes import TypeRegistry
from wandb.sdk.internal.internal_api import Api
from wandb.sdk.lib.filenames import DIFF_FNAME, METADATA_FNAME, REQUIREMENTS_FNAME
from wandb.util import make_artifact_name_safe

from .settings_static import SettingsStatic

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import ArtifactRecord

FROZEN_REQUIREMENTS_FNAME = "requirements.frozen.txt"
JOB_FNAME = "wandb-job.json"
JOB_ARTIFACT_TYPE = "job"

LOG_LEVEL = Literal["log", "warn", "error"]


class Version:
    def __init__(self, major: int, minor: int, patch: int):
        self._major = major
        self._minor = minor
        self._patch = patch

    def __repr__(self) -> str:
        return f"{self._major}.{self._minor}.{self._patch}"

    def __lt__(self, other: "Version") -> bool:
        if self._major < other._major:
            return True
        elif self._major == other._major:
            if self._minor < other._minor:
                return True
            elif self._minor == other._minor:
                if self._patch < other._patch:
                    return True
        return False

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (
            self._major == other._major
            and self._minor == other._minor
            and self._patch == other._patch
        )


# Minimum supported wandb version for keys in the source dict of wandb-job.json
SOURCE_KEYS_MIN_SUPPORTED_VERSION = {
    "dockerfile": Version(0, 17, 0),
    "build_context": Version(0, 17, 0),
}


class GitInfo(TypedDict):
    remote: str
    commit: str


class GitSourceDict(TypedDict):
    git: GitInfo
    entrypoint: List[str]
    notebook: bool
    build_context: Optional[str]
    dockerfile: Optional[str]


class ArtifactSourceDict(TypedDict):
    artifact: str
    entrypoint: List[str]
    notebook: bool
    build_context: Optional[str]
    dockerfile: Optional[str]


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


def get_min_supported_for_source_dict(
    source: Union[GitSourceDict, ArtifactSourceDict, ImageSourceDict],
) -> Optional[Version]:
    """Get the minimum supported wandb version the source dict of wandb-job.json."""
    min_seen = None
    for key in source:
        new_ver = SOURCE_KEYS_MIN_SUPPORTED_VERSION.get(key)
        if new_ver:
            if min_seen is None or new_ver < min_seen:
                min_seen = new_ver
    return min_seen


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
    _partial_source_id: Optional[str]  # Partial job source artifact id.
    _aliases: List[str]
    _job_seq_id: Optional[str]
    _job_version_alias: Optional[str]
    _is_notebook_run: bool
    _verbose: bool

    def __init__(self, settings: SettingsStatic, verbose: bool = False):
        self._settings = settings
        self._metadatafile_path = None
        self._requirements_path = None
        self._config = None
        self._summary = None
        self._logged_code_artifact = None
        self._job_seq_id = None
        self._job_version_alias = None
        self._disable = settings.disable_job_creation or settings.x_disable_machine_info
        self._partial_source_id = None
        self._aliases = []
        self._source_type: Optional[Literal["repo", "artifact", "image"]] = (
            settings.job_source  # type: ignore[assignment]
        )
        self._is_notebook_run = self._get_is_notebook_run()
        self._verbose = verbose
        self._partial = False

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

    @property
    def input_types(self) -> Dict[str, Any]:
        return TypeRegistry.type_of(self._config).to_json()

    @property
    def output_types(self) -> Dict[str, Any]:
        return TypeRegistry.type_of(self._summary).to_json()

    def set_partial_source_id(self, source_id: str) -> None:
        self._partial_source_id = source_id

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
        program_relpath: str,
        metadata: Dict[str, Any],
    ) -> Tuple[Optional[GitSourceDict], Optional[str]]:
        git_info: Dict[str, str] = metadata.get("git", {})
        remote = git_info.get("remote")
        commit = git_info.get("commit")
        root = metadata.get("root")
        assert remote is not None
        assert commit is not None
        if self._is_notebook_run:
            if not os.path.exists(
                os.path.join(os.getcwd(), os.path.basename(program_relpath))
            ):
                return None, None

            if root is None or self._settings.x_jupyter_root is None:
                _logger.info("target path does not exist, exiting")
                return None, None
            assert self._settings.x_jupyter_root is not None
            # git notebooks set the root to the git root,
            # jupyter_root contains the path where the jupyter notebook was started
            # program_relpath contains the path from jupyter_root to the file
            # full program path here is actually the relpath from the program to the git root
            full_program_path = os.path.join(
                os.path.relpath(str(self._settings.x_jupyter_root), root),
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

        entrypoint = self._get_entrypoint(full_program_path, metadata)
        # TODO: update executable to a method that supports pex
        source: GitSourceDict = {
            "git": {"remote": remote, "commit": commit},
            "entrypoint": entrypoint,
            "notebook": self._is_notebook_run,
            "build_context": metadata.get("build_context"),
            "dockerfile": metadata.get("dockerfile"),
        }
        name = self._make_job_name(f"{remote}_{program_relpath}")

        return source, name

    def _log_if_verbose(self, message: str, level: LOG_LEVEL) -> None:
        log_func: Optional[Union[Callable[[Any], None], Callable[[Any], None]]] = None
        if level == "log":
            _logger.info(message)
            log_func = wandb.termlog
        elif level == "warn":
            _logger.warning(message)
            log_func = wandb.termwarn
        elif level == "error":
            _logger.error(message)
            log_func = wandb.termerror

        if self._verbose and log_func is not None:
            log_func(message)

    def _build_artifact_job_source(
        self,
        program_relpath: str,
        metadata: Dict[str, Any],
    ) -> Tuple[Optional[ArtifactSourceDict], Optional[str]]:
        assert isinstance(self._logged_code_artifact, dict)
        # TODO: should we just always exit early if the path doesn't exist?
        if self._is_notebook_run and not self._is_colab_run():
            full_program_relpath = os.path.relpath(program_relpath, os.getcwd())
            # if the resolved path doesn't exist, then we shouldn't make a job because it will fail
            if not os.path.exists(full_program_relpath):
                # when users call log code in a notebook the code artifact starts
                # at the directory the notebook is in instead of the jupyter core
                if not os.path.exists(os.path.basename(program_relpath)):
                    _logger.info("target path does not exist, exiting")
                    self._log_if_verbose(
                        "No program path found when generating artifact job source for a non-colab notebook run. See https://docs.wandb.ai/guides/launch/create-job",
                        "warn",
                    )
                    return None, None
                full_program_relpath = os.path.basename(program_relpath)
        else:
            full_program_relpath = program_relpath

        entrypoint = self._get_entrypoint(full_program_relpath, metadata)
        # TODO: update executable to a method that supports pex
        source: ArtifactSourceDict = {
            "entrypoint": entrypoint,
            "notebook": self._is_notebook_run,
            "artifact": f"wandb-artifact://_id/{self._logged_code_artifact['id']}",
            "build_context": metadata.get("build_context"),
            "dockerfile": metadata.get("dockerfile"),
        }
        artifact_basename, *_ = self._logged_code_artifact["name"].split(":")
        name = self._make_job_name(artifact_basename)

        return source, name

    def _build_image_job_source(
        self, metadata: Dict[str, Any]
    ) -> Tuple[ImageSourceDict, str]:
        image_name = metadata.get("docker")
        assert isinstance(image_name, str)

        raw_image_name = image_name
        if ":" in image_name:
            tag = image_name.split(":")[-1]

            # if tag looks properly formatted, assume its a tag
            # regex: alphanumeric and "_" "-" "."
            if re.fullmatch(r"([a-zA-Z0-9_\-\.]+)", tag):
                raw_image_name = raw_image_name.replace(f":{tag}", "")
                self._aliases += [tag]

        source: ImageSourceDict = {
            "image": image_name,
        }
        name = self._make_job_name(raw_image_name)

        return source, name

    def _make_job_name(self, input_str: str) -> str:
        """Use job name from settings if provided, else use programmatic name."""
        if self._settings.job_name:
            return self._settings.job_name

        return make_artifact_name_safe(f"job-{input_str}")

    def _get_entrypoint(
        self,
        program_relpath: str,
        metadata: Dict[str, Any],
    ) -> List[str]:
        # if building a partial job from CLI, overwrite entrypoint and notebook
        # should already be in metadata from create_job
        if self._partial:
            if metadata.get("entrypoint"):
                entrypoint: List[str] = metadata["entrypoint"]
                return entrypoint
        # job is being built from a run
        entrypoint = [os.path.basename(sys.executable), program_relpath]

        return entrypoint

    def _get_is_notebook_run(self) -> bool:
        return hasattr(self._settings, "_jupyter") and bool(self._settings._jupyter)

    def _is_colab_run(self) -> bool:
        return hasattr(self._settings, "_colab") and bool(self._settings._colab)

    def _build_job_source(
        self,
        source_type: str,
        program_relpath: Optional[str],
        metadata: Dict[str, Any],
    ) -> Tuple[
        Union[GitSourceDict, ArtifactSourceDict, ImageSourceDict, None],
        Optional[str],
    ]:
        """Construct a job source dict and name from the current run.

        Args:
            source_type (str): The type of source to build the job from. One of
                "repo", "artifact", or "image".
        """
        source: Union[
            GitSourceDict,
            ArtifactSourceDict,
            ImageSourceDict,
            None,
        ] = None

        if source_type == "repo":
            source, name = self._build_repo_job_source(
                program_relpath or "",
                metadata,
            )
        elif source_type == "artifact":
            source, name = self._build_artifact_job_source(
                program_relpath or "",
                metadata,
            )
        elif source_type == "image" and self._has_image_job_ingredients(metadata):
            source, name = self._build_image_job_source(metadata)
        else:
            source = None

        if source is None:
            if source_type:
                self._log_if_verbose(
                    f"Source type is set to '{source_type}' but some required information is missing "
                    "from the environment. A job will not be created from this run. See "
                    "https://docs.wandb.ai/guides/launch/create-job",
                    "warn",
                )
            return None, None

        return source, name

    def build(
        self,
        api: Api,
        build_context: Optional[str] = None,
        dockerfile: Optional[str] = None,
        base_image: Optional[str] = None,
    ) -> Optional[Artifact]:
        """Build a job artifact from the current run.

        Args:
            api (Api): The API object to use to create the job artifact.
            build_context (Optional[str]): Path within the job source code to
                the image build context. Saved as part of the job for future
                builds.
            dockerfile (Optional[str]): Path within the build context the
                Dockerfile. Saved as part of the job for future builds.
            base_image (Optional[str]): The base image used to run the job code.

        Returns:
            Optional[Artifact]: The job artifact if it was successfully built,
            otherwise None.
        """
        _logger.info("Attempting to build job artifact")

        # If a partial job was used, write the input/output types to the metadata
        # rather than building a new job version.
        if self._partial_source_id is not None:
            new_metadata = {
                "input_types": {"@wandb.config": self.input_types},
                "output_types": self.output_types,
            }
            api.update_artifact_metadata(
                self._partial_source_id,
                new_metadata,
            )
            return None

        if not os.path.exists(
            os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME)
        ):
            self._log_if_verbose(
                "No requirements.txt found, not creating job artifact. See https://docs.wandb.ai/guides/launch/create-job",
                "warn",
            )
            return None
        metadata = self._handle_metadata_file()
        if metadata is None:
            self._log_if_verbose(
                f"Ensure read and write access to run files dir: {self._settings.files_dir}, control this via the WANDB_DIR env var. See https://docs.wandb.ai/guides/track/environment-variables",
                "warn",
            )
            return None

        runtime: Optional[str] = metadata.get("python")
        # can't build a job without a python version
        if runtime is None:
            self._log_if_verbose(
                "No python version found in metadata, not creating job artifact. "
                "See https://docs.wandb.ai/guides/launch/create-job",
                "warn",
            )
            return None

        input_types = TypeRegistry.type_of(self._config).to_json()
        output_types = TypeRegistry.type_of(self._summary).to_json()

        name: Optional[str] = None
        source_info: Optional[JobSourceDict] = None

        # configure job from environment
        source_type = self._get_source_type(metadata)
        if not source_type:
            # if source_type is None, then we don't have enough information to build a job
            # if the user intended to create a job, warn.
            if (
                self._settings.job_name
                or self._settings.job_source
                or self._source_type
            ):
                self._log_if_verbose(
                    "No source type found, not creating job artifact", "warn"
                )
            return None

        program_relpath = self._get_program_relpath(source_type, metadata)
        if not self._partial and source_type != "image" and not program_relpath:
            self._log_if_verbose(
                "No program path found, not creating job artifact. "
                "See https://docs.wandb.ai/guides/launch/create-job",
                "warn",
            )
            return None

        source, name = self._build_job_source(
            source_type,
            program_relpath,
            metadata,
        )
        if source is None:
            return None

        if build_context:
            source["build_context"] = build_context  # type: ignore[typeddict-item]
        if dockerfile:
            source["dockerfile"] = dockerfile  # type: ignore[typeddict-item]
        if base_image:
            source["base_image"] = base_image  # type: ignore[typeddict-item]

        # Pop any keys that are initialized to None. The current TypedDict
        # system for source dicts requires all keys to be present, but we
        # don't want to include keys that are None in the final dict.
        for key in list(source.keys()):
            if source[key] is None:  # type: ignore[literal-required]
                source.pop(key)  # type: ignore[literal-require,misc]

        source_info = {
            "_version": str(get_min_supported_for_source_dict(source) or "v0"),
            "source_type": source_type,
            "source": source,
            "input_types": input_types,
            "output_types": output_types,
            "runtime": runtime,
        }

        assert source_info is not None
        assert name is not None

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

    def _get_source_type(self, metadata: Dict[str, Any]) -> Optional[str]:
        if self._source_type:
            return self._source_type

        if self._has_git_job_ingredients(metadata):
            _logger.info("is repo sourced job")
            return "repo"

        if self._has_artifact_job_ingredients():
            _logger.info("is artifact sourced job")
            return "artifact"

        if self._has_image_job_ingredients(metadata):
            _logger.info("is image sourced job")
            return "image"

        _logger.info("no source found")
        return None

    def _get_program_relpath(
        self, source_type: str, metadata: Dict[str, Any]
    ) -> Optional[str]:
        if self._is_notebook_run:
            _logger.info("run is notebook based run")
            program = metadata.get("program")

            if not program:
                self._log_if_verbose(
                    "Notebook 'program' path not found in metadata. See https://docs.wandb.ai/guides/launch/create-job",
                    "warn",
                )

            return program

        if source_type == "artifact" or self._settings.job_source == "artifact":
            # if the job is set to be an artifact, use relpath guaranteed
            # to be correct. 'codePath' uses the root path when in git repo
            # fallback to codePath if strictly local relpath not present
            return metadata.get("codePathLocal") or metadata.get("codePath")

        return metadata.get("codePath")

    def _handle_metadata_file(
        self,
    ) -> Optional[Dict]:
        if os.path.exists(os.path.join(self._settings.files_dir, METADATA_FNAME)):
            with open(os.path.join(self._settings.files_dir, METADATA_FNAME)) as f:
                metadata: Dict = json.load(f)
            return metadata

        return None

    def _has_git_job_ingredients(self, metadata: Dict[str, Any]) -> bool:
        git_info: Dict[str, str] = metadata.get("git", {})
        if self._is_notebook_run and metadata.get("root") is None:
            return False
        return git_info.get("remote") is not None and git_info.get("commit") is not None

    def _has_artifact_job_ingredients(self) -> bool:
        return self._logged_code_artifact is not None

    def _has_image_job_ingredients(self, metadata: Dict[str, Any]) -> bool:
        return metadata.get("docker") is not None
