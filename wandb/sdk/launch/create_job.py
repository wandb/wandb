import json
import logging
import os
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import wandb
from wandb.apis.internal import Api
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.launch.git_reference import GitReference
from wandb.sdk.launch.utils import (
    _is_git_uri,
    get_current_python_version,
    get_entrypoint_file,
)
from wandb.sdk.lib import filesystem
from wandb.util import make_artifact_name_safe

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger("wandb")


CODE_ARTIFACT_EXCLUDE_PATHS = ["wandb", ".git"]


def create_job(
    path: str,
    job_type: str,
    entity: Optional[str] = None,
    project: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    runtime: Optional[str] = None,
    entrypoint: Optional[str] = None,
    git_hash: Optional[str] = None,
    build_context: Optional[str] = None,
    dockerfile: Optional[str] = None,
) -> Optional[Artifact]:
    """Create a job from a path, not as the output of a run.

    Arguments:
        path (str): Path to the job directory.
        job_type (str): Type of the job. One of "git", "code", or "image".
        entity (Optional[str]): Entity to create the job under.
        project (Optional[str]): Project to create the job under.
        name (Optional[str]): Name of the job.
        description (Optional[str]): Description of the job.
        aliases (Optional[List[str]]): Aliases for the job.
        runtime (Optional[str]): Python runtime of the job, like 3.9.
        entrypoint (Optional[str]): Entrypoint of the job. If build_context is
            provided, path is relative to build_context.
        git_hash (Optional[str]): Git hash of a specific commit, when using git type jobs.
        build_context (Optional[str]): Path to the build context, when using image type jobs.
        dockerfile (Optional[str]): Path to the Dockerfile, when using image type jobs.
            If build_context is provided, path is relative to build_context.

    Returns:
        Optional[Artifact]: The artifact created by the job, the action (for printing), and job aliases.
                            None if job creation failed.

    Example:
        ```python
        artifact_job = wandb.create_job(
            job_type="code",
            path=".",
            entity="wandb",
            project="jobs",
            name="my-train-job",
            description="My training job",
            aliases=["train"],
            runtime="3.9",
            entrypoint="train.py",
        )
        # then run the newly created job
        artifact_job.call()
        ```
    """
    api = Api()

    artifact_job, _action, _aliases = _create_job(
        api,
        job_type,
        path,
        entity,
        project,
        name,
        description,
        aliases,
        runtime,
        entrypoint,
        git_hash,
        build_context,
        dockerfile,
    )

    return artifact_job


def _create_job(
    api: Api,
    job_type: str,
    path: str,
    entity: Optional[str] = None,
    project: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    runtime: Optional[str] = None,
    entrypoint: Optional[str] = None,
    git_hash: Optional[str] = None,
    build_context: Optional[str] = None,
    dockerfile: Optional[str] = None,
    base_image: Optional[str] = None,
) -> Tuple[Optional[Artifact], str, List[str]]:
    wandb.termlog(f"Creating launch job of type: {job_type}...")

    if name and name != make_artifact_name_safe(name):
        wandb.termerror(
            f"Artifact names may only contain alphanumeric characters, dashes, underscores, and dots. Did you mean: {make_artifact_name_safe(name)}"
        )
        return None, "", []

    if runtime is not None:
        if not re.match(r"^3\.\d+$", runtime):
            wandb.termerror(
                f"Runtime (-r, --runtime) must be a minor version of Python 3, "
                f"e.g. 3.9 or 3.10, received {runtime}"
            )
            return None, "", []
    aliases = aliases or []
    tempdir = tempfile.TemporaryDirectory()
    try:
        metadata, requirements = _make_metadata_for_partial_job(
            job_type=job_type,
            tempdir=tempdir,
            git_hash=git_hash,
            runtime=runtime,
            path=path,
            entrypoint=entrypoint,
        )
        if not metadata:
            return None, "", []
    except Exception as e:
        wandb.termerror(f"Error creating job: {e}")
        return None, "", []

    _dump_metadata_and_requirements(
        metadata=metadata,
        tmp_path=tempdir.name,
        requirements=requirements,
    )

    try:
        # init hidden wandb run with job building disabled (handled manually)
        run = wandb.init(
            dir=tempdir.name,
            settings={"silent": True, "disable_job_creation": True},
            entity=entity,
            project=project,
            job_type="cli_create_job",
        )
    except Exception:
        # Error printed by wandb.init
        return None, "", []

    job_builder = _configure_job_builder_for_partial(tempdir.name, job_source=job_type)
    if job_type == "code":
        assert entrypoint is not None
        job_name = _make_code_artifact(
            api=api,
            job_builder=job_builder,
            path=path,
            entrypoint=entrypoint,
            run=run,  # type: ignore
            entity=entity,
            project=project,
            name=name,
        )
        if not job_name:
            return None, "", []
        name = job_name

    # build job artifact, loads wandb-metadata and creates wandb-job.json here
    artifact = job_builder.build(
        api.api,
        dockerfile=dockerfile,
        build_context=build_context,
        base_image=base_image,
    )
    if not artifact:
        wandb.termerror("JobBuilder failed to build a job")
        _logger.debug("Failed to build job, check job source and metadata")
        return None, "", []

    if not name:
        name = artifact.name

    aliases += job_builder._aliases
    if "latest" not in aliases:
        aliases += ["latest"]

    res, _ = api.create_artifact(
        artifact_type_name="job",
        artifact_collection_name=name,
        digest=artifact.digest,
        client_id=artifact._client_id,
        sequence_client_id=artifact._sequence_client_id,
        entity_name=entity,
        project_name=project,
        run_name=run.id,  # type: ignore # run will be deleted after creation
        description=description,
        metadata={"_partial": True},
        is_user_created=True,
        aliases=[{"artifactCollectionName": name, "alias": a} for a in aliases],
    )
    action = "No changes detected for"
    if not res.get("artifactSequence", {}).get("latestArtifact"):
        # When there is no latestArtifact, we are creating new
        action = "Created"
    elif res.get("state") == "PENDING":
        # updating an existing artifafct, state is pending awaiting call to
        # log_artifact to upload and finalize artifact. If not pending, digest
        # is the same as latestArtifact, so no changes detected
        action = "Updated"

    run.log_artifact(artifact, aliases=aliases)  # type: ignore
    artifact.wait()
    run.finish()  # type: ignore

    # fetch, then delete hidden run
    _run = wandb.Api().run(f"{entity}/{project}/{run.id}")  # type: ignore
    _run.delete()

    return artifact, action, aliases


def _make_metadata_for_partial_job(
    job_type: str,
    tempdir: tempfile.TemporaryDirectory,
    git_hash: Optional[str],
    runtime: Optional[str],
    path: str,
    entrypoint: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[List[str]]]:
    """Create metadata for partial jobs, return metadata and requirements."""
    metadata = {}
    if job_type == "git":
        assert entrypoint is not None
        repo_metadata = _create_repo_metadata(
            path=path,
            tempdir=tempdir.name,
            entrypoint=entrypoint,
            git_hash=git_hash,
            runtime=runtime,
        )
        if not repo_metadata:
            tempdir.cleanup()  # otherwise git can pollute
            return None, None
        metadata.update(repo_metadata)
        return metadata, None

    if job_type == "code":
        assert entrypoint is not None
        artifact_metadata, requirements = _create_artifact_metadata(
            path=path, entrypoint=entrypoint, runtime=runtime
        )
        if not artifact_metadata:
            return None, None
        metadata.update(artifact_metadata)
        return metadata, requirements

    if job_type == "image":
        if runtime:
            wandb.termwarn(
                "Setting runtime is not supported for image jobs, ignoring runtime"
            )
        # TODO(gst): support entrypoint for image based jobs
        if entrypoint:
            wandb.termwarn(
                "Setting an entrypoint is not currently supported for image jobs, ignoring entrypoint argument"
            )
        metadata.update({"python": runtime or "", "docker": path})
        return metadata, None

    wandb.termerror(f"Invalid job type: {job_type}")
    return None, None


def _maybe_warn_python_no_executable(entrypoint: str):
    entrypoint_list = entrypoint.split(" ")
    if len(entrypoint_list) == 1 and entrypoint_list[0].endswith(".py"):
        wandb.termwarn(
            f"Entrypoint {entrypoint} is a python file without an executable, you may want to use `python {entrypoint}` as the entrypoint instead."
        )


def _create_repo_metadata(
    path: str,
    tempdir: str,
    entrypoint: str,
    git_hash: Optional[str] = None,
    runtime: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    # Make sure the entrypoint doesn't contain any backward path traversal
    if entrypoint and ".." in entrypoint:
        wandb.termerror("Entrypoint cannot contain backward path traversal")
        return None

    _maybe_warn_python_no_executable(entrypoint)

    if not _is_git_uri(path):
        wandb.termerror("Path must be a git URI")
        return None

    ref = GitReference(path, git_hash)
    if not ref:
        wandb.termerror("Could not parse git URI")
        return None

    ref.fetch(tempdir)

    commit = ref.commit_hash
    if not commit:
        if not ref.commit_hash:
            wandb.termerror("Could not find git commit hash")
            return None
        commit = ref.commit_hash

    local_dir = os.path.join(tempdir, ref.path or "")
    python_version = runtime
    if not python_version:
        if os.path.exists(os.path.join(local_dir, "runtime.txt")):
            with open(os.path.join(local_dir, "runtime.txt")) as f:
                python_version = f.read().strip()
        elif os.path.exists(os.path.join(local_dir, ".python-version")):
            with open(os.path.join(local_dir, ".python-version")) as f:
                python_version = f.read().strip().splitlines()[0]
        else:
            python_version, _ = get_current_python_version()

    python_version = _clean_python_version(python_version)

    metadata = {
        "git": {
            "commit": commit,
            "remote": ref.url,
        },
        "entrypoint": entrypoint.split(" "),
        "python": python_version,  # used to build container
        "notebook": False,  # partial jobs from notebooks not supported
    }

    return metadata


def _create_artifact_metadata(
    path: str, entrypoint: str, runtime: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[List[str]]]:
    if not os.path.isdir(path):
        wandb.termerror("Path must be a valid file or directory")
        return {}, []

    _maybe_warn_python_no_executable(entrypoint)

    entrypoint_list = entrypoint.split(" ")
    entrypoint_file = get_entrypoint_file(entrypoint_list)

    # read local requirements.txt and dump to temp dir for builder
    requirements = []
    depspath = os.path.join(path, "requirements.txt")
    if os.path.exists(depspath):
        with open(depspath) as f:
            requirements = f.read().splitlines()

    if not any(["wandb" in r for r in requirements]):
        wandb.termwarn("wandb is not present in requirements.txt.")

    if runtime:
        python_version = _clean_python_version(runtime)
    else:
        python_version, _ = get_current_python_version()
        python_version = _clean_python_version(python_version)

    metadata = {
        "python": python_version,
        "codePath": entrypoint_file,
        "entrypoint": entrypoint_list,
    }
    return metadata, requirements


def _configure_job_builder_for_partial(tmpdir: str, job_source: str) -> JobBuilder:
    """Configure job builder with temp dir and job source."""
    # adjust git source to repo
    if job_source == "git":
        job_source = "repo"

    # adjust code source to artifact
    if job_source == "code":
        job_source = "artifact"

    settings = wandb.Settings()
    settings.update({"files_dir": tmpdir, "job_source": job_source})
    job_builder = JobBuilder(
        settings=settings,  # type: ignore
        verbose=True,
    )
    job_builder._partial = True
    # never allow notebook runs
    job_builder._is_notebook_run = False
    # set run inputs and outputs to empty dicts
    job_builder.set_config({})
    job_builder.set_summary({})
    return job_builder


def _make_code_artifact(
    api: Api,
    job_builder: JobBuilder,
    run: "wandb.sdk.wandb_run.Run",
    path: str,
    entrypoint: str,
    entity: Optional[str],
    project: Optional[str],
    name: Optional[str],
) -> Optional[str]:
    """Helper for creating and logging code artifacts.

    Returns the name of the eventual job.
    """
    entrypoint_list = entrypoint.split(" ")
    # We no longer require the entrypoint to end in an existing file. But we
    # need something to use as the default job artifact name. In the future we
    # may require the user to provide a job name explicitly when calling
    # wandb job create.
    entrypoint_file = entrypoint_list[-1]
    artifact_name = _make_code_artifact_name(os.path.join(path, entrypoint_file), name)
    code_artifact = wandb.Artifact(
        name=artifact_name,
        type="code",
        description="Code artifact for job",
    )

    try:
        code_artifact.add_dir(path)
    except Exception as e:
        if os.path.islink(path):
            wandb.termerror(
                "Symlinks are not supported for code artifact jobs, please copy the code into a directory and try again"
            )
        wandb.termerror(f"Error adding to code artifact: {e}")
        return None

    # Remove paths we don't want to include, if present
    for item in CODE_ARTIFACT_EXCLUDE_PATHS:
        try:
            code_artifact.remove(item)
        except FileNotFoundError:
            pass

    res, _ = api.create_artifact(
        artifact_type_name="code",
        artifact_collection_name=artifact_name,
        digest=code_artifact.digest,
        client_id=code_artifact._client_id,
        sequence_client_id=code_artifact._sequence_client_id,
        entity_name=entity,
        project_name=project,
        run_name=run.id,  # run will be deleted after creation
        description="Code artifact for job",
        metadata={"codePath": path, "entrypoint": entrypoint_file},
        is_user_created=True,
        aliases=[
            {"artifactCollectionName": artifact_name, "alias": a} for a in ["latest"]
        ],
    )
    run.log_artifact(code_artifact)
    code_artifact.wait()
    job_builder._handle_server_artifact(res, code_artifact)  # type: ignore

    # code artifacts have "code" prefix, remove it and alias
    if not name:
        name = code_artifact.name.replace("code", "job").split(":")[0]

    return name


def _make_code_artifact_name(path: str, name: Optional[str]) -> str:
    """Make a code artifact name from a path and user provided name."""
    if name:
        return f"code-{name}"

    clean_path = path.replace("./", "")
    if clean_path[0] == "/":
        clean_path = clean_path[1:]
    if clean_path[-1] == "/":
        clean_path = clean_path[:-1]

    path_name = f"code-{make_artifact_name_safe(clean_path)}"
    return path_name


def _dump_metadata_and_requirements(
    tmp_path: str, metadata: Dict[str, Any], requirements: Optional[List[str]]
) -> None:
    """Dump manufactured metadata and requirements.txt.

    File used by the job_builder to create a job from provided metadata.
    """
    filesystem.mkdir_exists_ok(tmp_path)
    with open(os.path.join(tmp_path, "wandb-metadata.json"), "w") as f:
        json.dump(metadata, f)

    requirements = requirements or []
    with open(os.path.join(tmp_path, "requirements.txt"), "w") as f:
        f.write("\n".join(requirements))


def _clean_python_version(python_version: str) -> str:
    # remove micro if present
    if python_version.count(".") > 1:
        python_version = ".".join(python_version.split(".")[:2])
        _logger.debug(f"micro python version stripped. Now: {python_version}")
    return python_version
