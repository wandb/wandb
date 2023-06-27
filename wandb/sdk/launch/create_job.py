import json
import logging
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import wandb
from wandb.apis.internal import Api
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.launch.builder.build import get_current_python_version
from wandb.sdk.launch.github_reference import GitHubReference
from wandb.sdk.launch.utils import _is_git_uri
from wandb.sdk.lib import filesystem
from wandb.util import make_artifact_name_safe

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger("wandb")


def create_job(
    path: str,
    entity: Optional[str] = None,
    project: Optional[str] = None,
    name: Optional[str] = None,
    job_type: Optional[str] = None,
    description: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    runtime: Optional[str] = None,
    entrypoint: Optional[str] = None,
    git_hash: Optional[str] = None,
) -> Optional[Artifact]:
    """Create a job from a path, not as the output of a run.

    Arguments:
        path (str): Path to the job directory.
        entity (str): Entity to create the job under.
        project (str): Project to create the job under.
        name (str): Name of the job.
        job_type (str): Type of the job. One of "repo", "artifact", or "image".
        description (str): Description of the job.
        aliases (List[str]): Aliases for the job.
        runtime (str): Python runtime of the job, like 3.9.
        entrypoint (str): Entrypoint of the job.
        git_hash (str): Git hash of a specific commit, when using repo type jobs.


    Returns:
        Optional[Artifact]: The artifact created by the job, the action (for printing), and job aliases.
                            None if job creation failed.

    Example:
        ```python
        artifact_job = wandb.create_job(
            path=".",
            entity="wandb",
            project="jobs",
            name="my-train-job",
            job_type="artifact",
            description="My training job",
            aliases=["train"],
            runtime="3.9",
            entrypoint="train.py",
        )
        # then, use you newly created job
        artifact_job.call()
        ```
    """
    api = Api()

    artifact_job, _action, _aliases = _create_job(
        api,
        path,
        entity,
        project,
        name,
        job_type,
        description,
        aliases,
        runtime,
        entrypoint,
        git_hash,
    )

    return artifact_job


def _create_job(
    api: Api,
    path: str,
    entity: Optional[str] = None,
    project: Optional[str] = None,
    name: Optional[str] = None,
    job_type: Optional[str] = None,
    description: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    runtime: Optional[str] = None,
    entrypoint: Optional[str] = None,
    git_hash: Optional[str] = None,
) -> Tuple[Optional[Artifact], str, List[str]]:
    aliases = aliases or []
    tempdir = tempfile.TemporaryDirectory()
    metadata = {"_proto": "v0"}  # seed metadata with special proto key
    requirements: List[str] = []

    # format relpaths, otherwise they can be interpreted as images
    if path[0] == "/":
        path = path[1:]

    if job_type == "repo":
        repo_metadata = _create_repo_metadata(
            path,
            tempdir.name,
            entrypoint,
            git_hash,
            runtime,
        )
        if not repo_metadata:
            tempdir.cleanup()  # otherwise git can pollute
            return None, "", []
        metadata.update(repo_metadata)
    elif job_type == "artifact":
        path, entrypoint = _handle_artifact_entrypoint(path, entrypoint)
        if not entrypoint:
            wandb.termerror(
                "Artifact jobs must have an entrypoint, either included in the path or specified with -E"
            )
            return None, "", []
        artifact_metadata, requirements = _create_artifact_metadata(
            path=path, entrypoint=entrypoint
        )
        if not artifact_metadata:
            return None, "", []
        metadata.update(artifact_metadata)
    elif job_type == "image":
        metadata.update({"python": "", "docker": path})
    else:
        wandb.termerror(f"Invalid job type: {job_type}")
        return None, "", []

    dump_metadata_and_requirements(
        metadata=metadata,
        tmp_path=tempdir.name,
        requirements=requirements,
    )

    # init hidden wandb run with job building disabled (handled manually)
    run = wandb.init(
        dir=tempdir.name,
        settings={"silent": True, "disable_job_creation": True},
        entity=entity,
        project=project,
        job_type="cli_create_job",
    )
    job_builder = _configure_job_builder(tempdir.name, job_source=job_type)
    if job_type == "artifact":
        full_path = os.path.join(path, entrypoint or "")
        artifact_name = make_code_artifact_name(full_path, name)
        code_artifact = wandb.Artifact(
            name=artifact_name,
            type="code",
            description="Code artifact for job",
        )
        code_artifact.add_dir(path)
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
            metadata={"codePath": path, "entrypoint": entrypoint},
            is_user_created=True,
            aliases=[
                {"artifactCollectionName": artifact_name, "alias": a} for a in aliases
            ],
        )
        run.log_artifact(code_artifact)
        code_artifact.wait()
        job_builder._set_logged_code_artifact(res, code_artifact)
        name = code_artifact.name.replace("code", "job").split(":")[0]

    # build job artifact, loads wandb-metadata and creates wandb-job.json here
    artifact = job_builder.build()
    if not artifact:
        wandb.termerror("JobBuilder failed to build a job")
        _logger.debug("Failed to build job, check job source and metadata")
        return None, "", []

    if not name:
        name = artifact.name
        wandb.termlog(f"No name provided, using default: {name}")

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
        run_name=run.id,  # run will be deleted after creation
        description=description,
        metadata=metadata,
        labels=["manually-created"],
        is_user_created=True,
        aliases=[{"artifactCollectionName": name, "alias": a} for a in aliases],
    )
    action = "No changes detected for"
    if not res.get("artifactSequence", {}).get("latestArtifact"):
        action = "Created"
    elif res.get("state") == "PENDING":
        action = "Updated"

    run.log_artifact(artifact, aliases=aliases)
    artifact.wait()
    run.finish()

    # fetch, then delete hidden run
    _run = wandb.Api().run(f"{entity}/{project}/{run.id}")
    _run.delete()

    return artifact, action, aliases


def _create_repo_metadata(
    path: str,
    tempdir: str,
    entrypoint: Optional[str] = None,
    git_hash: Optional[str] = None,
    runtime: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not _is_git_uri(path):
        wandb.termerror("Path must be a git URI")
        return None

    ref = GitHubReference.parse(path)
    if not ref:
        wandb.termerror("Could not parse git URI")
        return None

    commit = git_hash
    if not commit:
        ref.fetch(tempdir)
        if not ref.commit_hash:
            wandb.termerror("Could not find git commit hash")
            return None
        commit = ref.commit_hash
    ref_dir = ref.directory or ""
    src_dir = os.path.join(tempdir, ref_dir)
    python_version = runtime
    if not python_version:
        if os.path.exists(os.path.join(src_dir, "runtime.txt")):
            with open(os.path.join(src_dir, "runtime.txt")) as f:
                python_version = f.read().strip()
        elif os.path.exists(os.path.join(src_dir, ".python-version")):
            with open(os.path.join(src_dir, ".python-version")) as f:
                python_version = f.read().strip().splitlines()[0]
        else:
            major, minor = get_current_python_version()
            python_version = f"{major}.{minor}"

    # remove micro if present
    if python_version.count(".") > 1:
        python_version = ".".join(python_version.split(".")[:2])
        wandb.termwarn(
            f"Micro python versions not currently supported. Now: {python_version}"
        )

    if not os.path.exists(os.path.join(src_dir, "requirements.txt")):
        wandb.termerror(
            f"Could not find requirements.txt file in repo at: {ref.directory}/requirements.txt"
        )
        return None

    if not entrypoint:
        if os.path.exists(os.path.join(ref_dir, path.split("/")[-1])):
            entrypoint = os.path.join(ref_dir, path.split("/")[-1])
        else:
            wandb.termerror("Entrypoint not valid, specify one in the path or use -E")
            return None

    if entrypoint.strip().count(" ") > 0:
        # multi-word entrypoint implies command + codePath
        wandb.termerror(
            "For repo artifacts, the entrypoint must be only a path to a python file. Define the python runtime either by specifying it manually, or including a .python-version file in the repo root"
        )
        return None

    metadata = {
        "git": {
            "commit": commit,
            "remote": ref.url,
        },
        "root": ref.repo,
        "codePath": entrypoint,
        "python": python_version,  # used to build container
    }

    return metadata


def _create_artifact_metadata(
    path: str, entrypoint: str, runtime: Optional[str] = None
) -> Tuple[Dict[str, Any], List[str]]:
    if not os.path.exists(path):
        wandb.termerror("Path must be a valid file or directory")
        return {}, []

    if not os.path.exists(os.path.join(path, "requirements.txt")):
        wandb.termerror("Could not find requirements.txt file in local root")
        return {}, []

    # read local requirements.txt and dump to temp dir for builder
    requirements = []
    with open(os.path.join(path, "requirements.txt")) as f:
        requirements = f.read().splitlines()

    python_version = runtime or ".".join(get_current_python_version())
    metadata = {"python": python_version, "codePath": entrypoint}
    return metadata, requirements


def _handle_artifact_entrypoint(
    path: str, entrypoint: Optional[str] = None
) -> Tuple[str, Optional[str]]:
    if os.path.isfile(path):
        if entrypoint:
            wandb.termwarn("Ignoring entrypoint as path is to a file")
        entrypoint = path.split("/")[-1]
        path = "/".join(path.split("/")[:-1]) or "."
    return path, entrypoint


def _configure_job_builder(tmpdir: str, job_source: str) -> JobBuilder:
    """Configure job builder with temp dir and job source."""
    settings = wandb.Settings()
    settings.update({"files_dir": tmpdir, "job_source": job_source})
    job_builder = JobBuilder(
        settings=settings,
    )
    # set run inputs and outputs to empty dicts
    job_builder.set_config({})
    job_builder.set_summary({})
    return job_builder


def make_code_artifact_name(path: str, name: Optional[str]) -> str:
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


def dump_metadata_and_requirements(
    tmp_path: str, metadata: Dict[str, Any], requirements: List[str]
) -> None:
    """Dump manufactured metadata and requirements.txt.

    File used by the job_builder to create a job from provided metadata.
    """
    filesystem.mkdir_exists_ok(tmp_path)
    with open(os.path.join(tmp_path, "wandb-metadata.json"), "w") as f:
        json.dump(metadata, f)

    with open(os.path.join(tmp_path, "requirements.txt"), "w") as f:
        f.write("\n".join(requirements))
