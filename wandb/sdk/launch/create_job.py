import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import yaml

import wandb
from wandb.apis.internal import Api
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal.job_builder import FROZEN_CONDA_FNAME, JobBuilder
from wandb.sdk.launch.builder.build import list_conda_envs
from wandb.sdk.launch.git_reference import GitReference
from wandb.sdk.launch.utils import (
    _is_git_uri,
    get_current_python_version,
    get_entrypoint_file,
)
from wandb.sdk.lib.gitlib import GitRepo
from wandb.util import make_artifact_name_safe

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger("wandb")


CODE_ARTIFACT_EXCLUDE_PATHS = ["wandb", ".git", ".ipynb_checkpoints", "artifacts"]


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
        path (str): Path to the job directory or entrypoint.
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
        build_context (Optional[str]): Path to the build context when using image type jobs
            or the directory where the command will be run from for other job types.
        dockerfile (Optional[str]): Path to the Dockerfile, when using image type jobs.
            If build_context is provided, path is relative to build_context.

    Returns:
        Optional[Artifact]: The artifact created by the job, or None if job creation failed.

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

    local_repo = not (path.startswith("git@") or path.startswith("http"))

    root = os.getcwd()
    slurm = True if entrypoint and "sbatch " in entrypoint else False
    path, entrypoint, slurm, new_build_context, hash, root_dir = _job_args_from_path(
        path, job_type, slurm, entrypoint, build_context
    )
    if build_context is None:
        wandb.termlog(
            f"Script will be run from {new_build_context}, pass --build_context . to override"
        )
        build_context = new_build_context
    if root_dir is not None:
        root = root_dir
    if git_hash is None:
        git_hash = hash
        if git_hash is not None:
            wandb.termlog(f"Using git ref {git_hash}, use --git-hash to override")

    aliases = aliases or []
    tempdir = tempfile.TemporaryDirectory()
    try:
        metadata = _make_metadata_for_partial_job(
            job_type=job_type,
            tempdir=tempdir,
            git_hash=git_hash,
            runtime=runtime,
            path=path,
            entrypoint=entrypoint,
            slurm=slurm,
        )
        if not metadata:
            return None, "", []
    except Exception as e:
        wandb.termerror(f"Error creating job: {e}")
        return None, "", []

    requirements_file = _dump_metadata_and_find_requirements(
        metadata=metadata,
        tmp_path=tempdir.name,
        root_path=root,
        build_context=build_context,
        requirement_files=["environment.yml"] if slurm else ["requirements.txt"],
    )

    # TODO: for now we're only handling conda environments for slurm jobs when created
    # from a local repo or directory.  We can likely add support for pip virtualenvs
    # or add more general support for conda environments in the future
    if job_type != "image" and slurm and local_repo:
        frozen_requirements_file = _create_frozen_requirements(
            tempdir, requirements_file
        )
        if frozen_requirements_file:
            requirements_file = frozen_requirements_file
        elif requirements_file is not None:
            wandb.termwarn(
                f"Couldn't freeze conda environment, using {requirements_file}"
            )
        else:
            wandb.termwarn(
                "Couldn't find or create a conda environment, aborting job creation"
            )
            return None, "", []

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
        requirements_file=requirements_file,
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


def _create_frozen_requirements(
    tempdir: tempfile.TemporaryDirectory, requirements_file: Optional[str]
) -> Optional[str]:
    """Create a frozen requirements file from the current environment.

    It first check if the current shell is a conda environment, and if so, it uses conda env export
    to create a frozen environment.yml file. If the current shell is not a conda environment,
    it uses pip freeze to create a frozen requirements.txt file.
    """
    current_shell_is_conda = os.path.exists(os.path.join(sys.prefix, "conda-meta"))
    if current_shell_is_conda:
        env_name = None
        # TODO: handle found requirements.txt in a conda environment
        if requirements_file and requirements_file.endswith(".yml"):
            try:
                with open(requirements_file) as f:
                    env_name = yaml.load(f, Loader=yaml.Loader).get("name")
            except yaml.YAMLError:
                wandb.termwarn(
                    f"Error loading conda environment file {os.path.relpath(requirements_file)}, ignoring"
                )
        try:
            if env_name is None:
                env_name = os.getenv("CONDA_DEFAULT_ENV") or "base"
            elif env_name not in list_conda_envs():
                wandb.termwarn(
                    f"Conda environment {env_name} not found, be sure to create it in your environment."
                )
                # TODO: test this is handled properly
                return None
            wandb.termlog(
                f"Detected conda environment, generating frozen env file from {env_name}..."
            )
            with open(os.path.join(tempdir.name, FROZEN_CONDA_FNAME), "w") as f:
                subprocess.call(
                    ["conda", "env", "export", "--name", env_name],
                    stdout=f,
                    stderr=subprocess.DEVNULL,
                    timeout=15,  # add timeout since conda env export could take a really long time
                )
            # TODO: add remove renaming logic from the build step
            requirements_file = os.path.join(tempdir.name, FROZEN_CONDA_FNAME)
        except Exception as e:
            wandb.termwarn(f"Error saving conda environment: {e}")
            return None
    else:
        wandb.termwarn(
            "No conda environment found, slurm jobs only support conda environments currently"
        )
        # TODO: consider creating a virtualenv then freezing if we have a requirements.txt
        # requirements_file = get_local_python_deps(
        #    tempdir.name, FROZEN_REQUIREMENTS_FNAME
        # )
        return None
    return requirements_file


def _ensure_entrypoint(job_type: str, entrypoint: Optional[str]) -> str:
    if entrypoint is None and job_type in ["git", "code"]:
        wandb.termwarn(
            f"No entrypoint provided for {job_type} job, defaulting to main.py"
        )
        return "main.py"
    return entrypoint


def _job_args_from_path(
    path: str,
    job_type: str,
    slurm: bool,
    entrypoint: Optional[str],
    build_context: Optional[str],
) -> Tuple[str, str, bool, Optional[str], Optional[str], Optional[str]]:
    """Given a path, return a new path along with entrypoint, slurm, build_context, hash, and root."""
    hash = None
    if job_type == "git":
        # git@github.com/wandb/launch-jobs.git@main
        if path.startswith("git@"):
            uri = urlparse("git+ssh://" + path)
            if "@" in uri.path:
                hash = path.split("@")[-1]
                path = path.replace(f"@{hash}", "")
            return (
                path,
                _ensure_entrypoint(job_type, entrypoint),
                slurm,
                build_context,
                hash,
                None,
            )

        # https://github.com/wandb/launch-jobs.git@main
        uri = urlparse(path)
        if uri.netloc:
            if "@" in uri.path:
                hash = uri.path.split("@")[-1]
                path = path.split("@")[0]
            return (
                path,
                _ensure_entrypoint(job_type, entrypoint),
                slurm,
                build_context,
                hash,
                None,
            )

        # ./my-project/my-script.sh
        repo = GitRepo(os.path.dirname(uri.path))
        root_dir = repo.root_dir
        if root_dir is None:
            wandb.termwarn(
                f"Could not find git repo for {uri.path}, use 'code' job type instead"
            )
            root_dir = os.getcwd()
            # TODO: should we error here?
        else:
            path = repo.remote_url
            hash = repo.branch
        if os.path.exists(uri.path) and os.path.isfile(uri.path):
            # Auto detect slurm
            if not slurm:
                with open(uri.path) as f:
                    body = f.read()
                    slurm = "#SBATCH " in body or "srun " in body
                if slurm:
                    wandb.termlog(
                        "Detected slurm sbatch script, marking job as slurm compatible"
                    )
            cwd_rel_path = os.path.relpath(os.getcwd(), root_dir)
            repo_rel_path = os.path.relpath(
                os.path.dirname(os.path.abspath(uri.path)), root_dir
            )
            # TODO: better error here?
            assert ".." not in repo_rel_path, "path cannot contain .."
            # TODO: handle abs path?
            script = uri.path
            if build_context is None and cwd_rel_path != ".":
                build_context = cwd_rel_path
            if entrypoint is None:
                if slurm:
                    entrypoint = f"sbatch {script}"
                else:
                    entrypoint = script
        elif not os.path.exists(uri.path):
            wandb.termwarn(
                f"Path {os.path.abspath(uri.path)} does not exist, maybe this was a typo?"
            )
    elif job_type == "code":
        # TODO: build_context for code jobs?
        if os.path.exists(path) and os.path.isfile(path):
            entrypoint = path
    return (
        path,
        _ensure_entrypoint(job_type, entrypoint),
        slurm,
        build_context,
        hash,
        root_dir,
    )


def _make_metadata_for_partial_job(
    job_type: str,
    tempdir: tempfile.TemporaryDirectory,
    git_hash: Optional[str],
    runtime: Optional[str],
    path: str,
    entrypoint: Optional[str],
    slurm: Optional[bool] = False,
) -> Optional[Dict[str, Any]]:
    """Create metadata for partial jobs, return metadata and requirements."""
    metadata = {}
    # TODO (slurm): maybe add other metadata here?
    if slurm:
        metadata["slurm"] = True
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
        return metadata

    if job_type == "code":
        assert entrypoint is not None
        artifact_metadata = _create_artifact_metadata(
            path=path, entrypoint=entrypoint, runtime=runtime
        )
        if not artifact_metadata:
            return None, None
        metadata.update(artifact_metadata)
        return metadata

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
        return metadata

    wandb.termerror(f"Invalid job type: {job_type}")
    return None


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

    # TODO: we should verify the entrypoint file exists
    # TODO: we should verify the path we're adding doesn't have uncommitted changes

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
) -> Optional[Dict[str, Any]]:
    if not os.path.isdir(path):
        wandb.termerror("Path must be a valid file or directory")
        return None

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
    return metadata


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
    # TODO: we should probably check for files larger than a certain size here and not include them

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


def _find_requirements_or_environment_yml(
    root: str, build_context: Optional[str], requirement_files: List[str]
) -> Optional[str]:
    for path in requirement_files:
        if build_context and os.path.exists(os.path.join(root, build_context, path)):
            return os.path.abspath(os.path.join(root, build_context, path))
        if os.path.exists(os.path.join(root, path)):
            return os.path.abspath(os.path.join(root, path))
    return None


def _dump_metadata_and_find_requirements(
    tmp_path: str,
    root_path: Optional[str],
    metadata: Dict[str, Any],
    build_context: Optional[str],
    requirement_files: List[str],
) -> Optional[str]:
    """Dump manufactured metadata and find requirements.txt or environment.yml.

    We look in our temp dir first, then we look in the local build context.

    Returns the found requirements.txt or environment.yml absolute path.
    """
    with open(os.path.join(tmp_path, "wandb-metadata.json"), "w") as f:
        json.dump(metadata, f)

    path = _find_requirements_or_environment_yml(
        tmp_path, build_context, requirement_files
    )
    if path:
        return path
    else:
        return _find_requirements_or_environment_yml(
            root_path, build_context, requirement_files
        )


def _clean_python_version(python_version: str) -> str:
    # remove micro if present
    if python_version.count(".") > 1:
        python_version = ".".join(python_version.split(".")[:2])
        _logger.debug(f"micro python version stripped. Now: {python_version}")
    return python_version
