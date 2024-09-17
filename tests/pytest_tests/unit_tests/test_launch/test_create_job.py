import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.launch.create_job import (
    _configure_job_builder_for_partial,
    _create_artifact_metadata,
    _create_repo_metadata,
    _dump_metadata_and_find_requirements,
    _job_args_from_path,
    _make_code_artifact_name,
)
from wandb.sdk.launch.utils import get_current_python_version


def test_create_artifact_metadata(mocker):
    mocker.termwarn = MagicMock()
    mocker.patch("wandb.termwarn", mocker.termwarn)
    path = tempfile.TemporaryDirectory().name
    runtime = "3.9"
    entrypoint = "python test.py"
    entrypoint_list = ["python", "test.py"]
    entrypoint_file = "test.py"

    # files don't exist yet
    metadata = _create_artifact_metadata(path, entrypoint, runtime)
    assert not metadata

    # wandb missing
    os.makedirs(path)
    with open(os.path.join(path, "requirements.txt"), "w") as f:
        f.write("test-import\n")
    metadata = _create_artifact_metadata(path, entrypoint, runtime)
    assert metadata == {
        "python": runtime,
        "codePath": entrypoint_file,
        "entrypoint": entrypoint_list,
    }
    warn_msg = mocker.termwarn.call_args.args[0]
    assert "wandb is not present in requirements.txt." in warn_msg
    mocker.termwarn.reset_mock()

    # basic case
    with open(os.path.join(path, "requirements.txt"), "a") as f:
        f.write("wandb\n")
    metadata = _create_artifact_metadata(path, entrypoint, runtime)
    assert metadata == {
        "python": runtime,
        "codePath": entrypoint_file,
        "entrypoint": entrypoint_list,
    }
    mocker.termwarn.assert_not_called()

    # python picked up correctly
    metadata = _create_artifact_metadata(path, entrypoint)
    py, _ = get_current_python_version()
    assert metadata == {
        "python": py,
        "codePath": entrypoint_file,
        "entrypoint": entrypoint_list,
    }


def test_configure_job_builder_for_partial():
    dir = tempfile.TemporaryDirectory().name
    job_source = "repo"

    builder = _configure_job_builder_for_partial(dir, job_source)
    assert isinstance(builder, JobBuilder)
    assert builder._config == {}
    assert builder._summary == {}
    assert builder._settings.get("files_dir") == dir
    assert builder._settings.get("job_source") == job_source


def test_make_code_artifact_name():
    name = "karen"

    assert _make_code_artifact_name("./test", name) == f"code-{name}"
    assert _make_code_artifact_name("./test", None) == "code-test"
    assert _make_code_artifact_name("test", None) == "code-test"
    assert _make_code_artifact_name("/test", None) == "code-test"
    assert _make_code_artifact_name("/test/", None) == "code-test"
    assert _make_code_artifact_name("./test/", None) == "code-test"

    assert _make_code_artifact_name("/test/dir", None) == "code-test_dir"
    assert _make_code_artifact_name("./test/dir/", None) == "code-test_dir"


def test_dump_metadata_and_find_requirements():
    with tempfile.TemporaryDirectory() as path:
        metadata = {"testing": "123"}
        requirements = os.path.join(path, "requirements.txt")
        with open(requirements, "w") as f:
            f.write("wandb\n")
        requirement_files = ["requirements.txt"]

        found_requirements = _dump_metadata_and_find_requirements(
            path, os.getcwd(), metadata, None, requirement_files
        )

        assert found_requirements == requirements
        assert os.path.exists(os.path.join(path, "wandb-metadata.json"))

        with open(requirements) as f:
            assert f.read().strip().splitlines() == ["wandb"]

        m = json.load(open(os.path.join(path, "wandb-metadata.json")))
        assert metadata == m


def test_job_args_from_path_git_remote():
    http_simple = "https://github.com/wandb/wandb.git"
    http_branch = "https://github.com/wandb/wandb.git@foo"
    ssh_simple = "git@github.com:wandb/wandb.git"
    ssh_hash = "git@github.com:wandb/wandb.git@foo"
    job_type = "git"
    build_context = "subdir"
    result = _job_args_from_path(http_simple, job_type, False, None, build_context)
    assert result == (http_simple, "main.py", False, build_context, None, None)
    result = _job_args_from_path(http_branch, job_type, False, None, build_context)
    assert result == (http_simple, "main.py", False, build_context, "foo", None)
    result = _job_args_from_path(ssh_simple, job_type, False, None, build_context)
    assert result == (ssh_simple, "main.py", False, build_context, None, None)
    result = _job_args_from_path(ssh_hash, job_type, False, None, build_context)
    assert result == (ssh_simple, "main.py", False, build_context, "foo", None)


def test_job_args_from_path_git_local(git_repo):
    git_repo.repo.create_remote("origin", "https://github.com/wandb/launch-jobs.git")
    git_path = git_repo.root_dir
    os.makedirs(os.path.join(git_path, "subdir"), exist_ok=True)
    with open(os.path.join(git_path, "subdir", "test.py"), "w") as f:
        f.write("print('hello world')")
    git_repo.repo.index.add(["subdir/test.py"])
    git_repo.repo.index.commit("test commit")
    os.makedirs(os.path.join(git_path, "otherdir"), exist_ok=True)
    with open(os.path.join(git_path, "otherdir", "slurm.sh"), "w") as f:
        f.write("#SBATCH --nnodes=5")
    job_type = "git"
    # build context override, this will error out later
    build_context = "baddir"
    result = _job_args_from_path(
        "./subdir/test.py", job_type, False, None, build_context
    )
    assert result == (
        "https://github.com/wandb/launch-jobs.git",
        "./subdir/test.py",
        False,
        "baddir",
        "main",
        git_path,
    )
    # slurm detection and relative path
    result = _job_args_from_path("./otherdir/slurm.sh", job_type, False, None, None)
    assert result == (
        "https://github.com/wandb/launch-jobs.git",
        "sbatch ./otherdir/slurm.sh",
        True,
        None,
        "main",
        git_path,
    )
    # context relative to cwd
    os.chdir("./subdir")
    result = _job_args_from_path("./test.py", job_type, False, None, None)
    assert result == (
        "https://github.com/wandb/launch-jobs.git",
        "./test.py",
        False,
        "subdir",
        "main",
        git_path,
    )
    # non-default branch
    test_branch = git_repo.repo.create_head("test-branch")
    test_branch.checkout()
    result = _job_args_from_path("./test.py", job_type, False, None, None)
    assert result == (
        "https://github.com/wandb/launch-jobs.git",
        "./test.py",
        False,
        "subdir",
        "test-branch",
        git_path,
    )
    # TODO: test path with .. and absolute path


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="python exec name is different on windows",
)
def test_get_entrypoint():
    dir = tempfile.TemporaryDirectory().name
    job_source = "artifact"
    builder = _configure_job_builder_for_partial(dir, job_source)
    python_executable = os.path.basename(sys.executable)

    metadata = {"python": "3.9.11", "codePathLocal": "main.py", "_partial": "v0"}

    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)
    assert entrypoint == [python_executable, "main.py"]

    metadata = {"python": "3.9", "codePath": "main.py", "_partial": "v0"}
    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)
    assert entrypoint == [python_executable, "main.py"]

    metadata = {"codePath": "main.py"}
    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)

    assert entrypoint == [python_executable, "main.py"]


def test_create_repo_metadata_entrypoint_traversal():
    result = _create_repo_metadata(
        "", "", entrypoint="../../../../../usr/bin/python3.9 main.py"
    )
    assert result is None


def test_create_repo_metadata_custom_dockerfile(monkeypatch, tmp_path):
    """This should succeed even thought there is no requirements.txt file because the dockerfile is specified."""
    entrypoint = "subdir/main.py"
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "main.py").write_text("print('hello world')")
    (subdir / "Dockerfile.wandb").write_text("FROM python:3.9")

    mock_git_ref = MagicMock(
        return_value=MagicMock(
            commit_hash="1234567890",
            fetch=MagicMock(),
            path=tmp_path,
        )
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.create_job.GitReference",
        lambda *args: mock_git_ref(*args),
    )
    result = _create_repo_metadata(
        "https://github.com/wandb/wandb.git", str(tmp_path), entrypoint=entrypoint
    )
    assert result is not None

    # dockerfile.write_text("FROM python:3.9")
    # result = _create_repo_metadata("", "", dockerfile=dockerfile)
    # assert result["dockerfile"] == "Dockerfile"


def test_create_frozen_requirements(monkeypatch):
    from wandb.sdk.launch.create_job import _create_frozen_requirements

    # Mock the subprocess.call function
    mock_subprocess_call = MagicMock()
    monkeypatch.setattr("subprocess.call", mock_subprocess_call)

    # Mock the list_conda_envs function
    mock_list_conda_envs = MagicMock(return_value=["base", "test_env"])
    monkeypatch.setattr(
        "wandb.sdk.launch.create_job.list_conda_envs", mock_list_conda_envs
    )

    # Create a temporary directory
    tempdir = tempfile.TemporaryDirectory()
    temppath = Path(tempdir.name)

    # Test case 1: Conda environment
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "test_env")
    monkeypatch.setattr("os.path.exists", lambda x: "conda-meta" in x)

    result = _create_frozen_requirements(tempdir, None)

    assert result == str(temppath / "conda.frozen.yml")
    mock_subprocess_call.assert_called_once_with(
        ["conda", "env", "export", "--name", "test_env"],
        stdout=mock_subprocess_call.call_args[1]["stdout"],
        stderr=subprocess.DEVNULL,
        timeout=15,
    )

    # Reset mocks
    mock_subprocess_call.reset_mock()

    # Test case 2: Non-conda environment
    monkeypatch.delenv("CONDA_DEFAULT_ENV")
    monkeypatch.setattr("os.path.exists", lambda x: "conda-meta" not in x)

    result = _create_frozen_requirements(tempdir, None)

    assert result is None
    mock_subprocess_call.assert_not_called()

    # Test case 3: Conda environment with existing requirements.yml
    monkeypatch.setattr("os.path.exists", lambda x: "conda-meta" in x)
    requirements_file = temppath / "environment.yml"
    requirements_file.write_text("name: test_env\ndependencies:\n  - python=3.8\n")

    result = _create_frozen_requirements(tempdir, str(requirements_file))

    assert result == str(temppath / "conda.frozen.yml")
    mock_subprocess_call.assert_called_once_with(
        ["conda", "env", "export", "--name", "test_env"],
        stdout=mock_subprocess_call.call_args[1]["stdout"],
        stderr=subprocess.DEVNULL,
        timeout=15,
    )

    # Test case 4: conda environment not found
    with open(requirements_file, "w") as f:
        f.write("name: nonexistent_env")
    result = _create_frozen_requirements(tempdir, str(requirements_file))
    assert result is None
