import json
import os
import platform
import sys
import tempfile

import pytest
from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.launch.builder.build import get_current_python_version
from wandb.sdk.launch.create_job import (
    _configure_job_builder_for_partial,
    _create_artifact_metadata,
    _dump_metadata_and_requirements,
    _handle_artifact_entrypoint,
    _make_code_artifact_name,
)


def test_create_artifact_metadata():
    path = tempfile.TemporaryDirectory().name
    runtime = "3.9"
    entrypoint = "test.py"

    # files don't exist yet
    metadata, requirements = _create_artifact_metadata(path, entrypoint, runtime)
    assert not metadata and not requirements

    os.makedirs(path)
    # path exists, no requirements, still should fail
    metadata, requirements = _create_artifact_metadata(path, entrypoint, runtime)
    assert not metadata and not requirements

    with open(os.path.join(path, "requirements.txt"), "w") as f:
        f.write("wandb\n")

    # basic case
    metadata, requirements = _create_artifact_metadata(path, entrypoint, runtime)
    assert metadata == {"python": runtime, "codePath": entrypoint}
    assert requirements == ["wandb"]

    # python picked up correctly
    metadata, requirements = _create_artifact_metadata(path, entrypoint)
    py = ".".join(get_current_python_version())
    assert metadata == {"python": py, "codePath": entrypoint}
    assert requirements == ["wandb"]


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Windows base path if empty is broken, TODO"
)
def test_handle_artifact_entrypoint():
    path = tempfile.TemporaryDirectory().name
    entrypoint = "test.py"

    os.makedirs(path)

    out_path, out_entrypoint = _handle_artifact_entrypoint(path, None)
    assert not out_path  # path isn't to file and entrypoint is None

    with open(os.path.join(path, entrypoint), "w") as f:
        f.write("print('hello world')")

    out_path, out_entrypoint = _handle_artifact_entrypoint(path, entrypoint)
    assert out_path == path and out_entrypoint == entrypoint

    joined_path = os.path.join(path, entrypoint)
    out_path, out_entrypoint = _handle_artifact_entrypoint(joined_path)

    assert out_path == path, out_entrypoint == entrypoint


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


def test__get_entrypoint():
    dir = tempfile.TemporaryDirectory().name
    job_source = "artifact"
    builder = _configure_job_builder_for_partial(dir, job_source)

    metadata = {"python": "3.9.11", "codePathLocal": "main.py", "_partial": "v0"}

    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)
    assert entrypoint == ["python3.9", "main.py"]

    metadata = {"python": "3.9", "codePath": "main.py", "_partial": "v0"}
    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)
    assert entrypoint == ["python3.9", "main.py"]

    with pytest.raises(AssertionError):
        metadata = {"codePath": "main.py", "_partial": "v0"}
        program_relpath = builder._get_program_relpath(job_source, metadata)
        entrypoint = builder._get_entrypoint(program_relpath, metadata)

    metadata = {"codePath": "main.py"}
    program_relpath = builder._get_program_relpath(job_source, metadata)
    entrypoint = builder._get_entrypoint(program_relpath, metadata)

    assert entrypoint == [os.path.basename(sys.executable), "main.py"]
