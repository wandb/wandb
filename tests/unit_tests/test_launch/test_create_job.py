import json
import os
import platform
import sys
import tempfile
from unittest.mock import MagicMock

import pytest
from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.launch.create_job import (
    _configure_job_builder_for_partial,
    _create_artifact_metadata,
    _create_repo_metadata,
    _dump_metadata_and_requirements,
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
    metadata, requirements = _create_artifact_metadata(path, entrypoint, runtime)
    assert not metadata and not requirements

    # wandb missing
    os.makedirs(path)
    with open(os.path.join(path, "requirements.txt"), "w") as f:
        f.write("test-import\n")
    metadata, requirements = _create_artifact_metadata(path, entrypoint, runtime)
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
    metadata, requirements = _create_artifact_metadata(path, entrypoint, runtime)
    assert metadata == {
        "python": runtime,
        "codePath": entrypoint_file,
        "entrypoint": entrypoint_list,
    }
    assert requirements == ["test-import", "wandb"]
    mocker.termwarn.assert_not_called()

    # python picked up correctly
    metadata, requirements = _create_artifact_metadata(path, entrypoint)
    py, _ = get_current_python_version()
    assert metadata == {
        "python": py,
        "codePath": entrypoint_file,
        "entrypoint": entrypoint_list,
    }
    assert requirements == ["test-import", "wandb"]


def test_configure_job_builder_for_partial():
    dir = tempfile.TemporaryDirectory().name
    job_source = "repo"

    builder = _configure_job_builder_for_partial(dir, job_source)
    assert isinstance(builder, JobBuilder)
    assert builder._config == {}
    assert builder._summary == {}
    assert builder._files_dir == dir
    assert builder._settings.job_source == job_source


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


def test_dump_metadata_and_requirements():
    path = tempfile.TemporaryDirectory().name
    metadata = {"testing": "123"}
    requirements = ["wandb", "optuna"]

    _dump_metadata_and_requirements(path, metadata, requirements)

    assert os.path.exists(os.path.join(path, "requirements.txt"))
    assert os.path.exists(os.path.join(path, "wandb-metadata.json"))

    with open(os.path.join(path, "requirements.txt")) as f:
        assert f.read().strip().splitlines() == requirements

    m = json.load(open(os.path.join(path, "wandb-metadata.json")))
    assert metadata == m


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="python exec name is different on windows",
)
def test_get_entrypoint():
    dir = tempfile.TemporaryDirectory().name
    job_source = "artifact"
    builder = _configure_job_builder_for_partial(dir, job_source)

    metadata = {"python": "3.9.11", "codePathLocal": "main.py", "_partial": "v0"}

    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)
    assert entrypoint == ["python3", "main.py"]

    metadata = {"python": "3.9", "codePath": "main.py", "_partial": "v0"}
    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)
    assert entrypoint == ["python3", "main.py"]

    metadata = {"codePath": "main.py"}
    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)

    assert entrypoint == [os.path.basename(sys.executable), "main.py"]


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
