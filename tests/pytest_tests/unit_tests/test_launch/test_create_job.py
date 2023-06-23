import tempfile
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.launch.builder.build import get_current_python_version
from wandb.sdk.launch.create_job import (
    _create_artifact_metadata,
    _handle_artifact_entrypoint,
    _configure_job_builder,
    make_code_artifact_name,
    dump_metadata_and_requirements,
    create_job,
)

import os
import sys
import json


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


def test_handle_artifact_entrypoint():
    path = tempfile.TemporaryDirectory().name
    entrypoint = "test.py"

    os.makedirs(path)

    out_path, out_entrypoint = _handle_artifact_entrypoint(path, None)
    assert out_path == path and not out_entrypoint

    out_path, out_entrypoint = _handle_artifact_entrypoint(path, entrypoint)
    assert out_path == path and out_entrypoint == entrypoint

    with open(os.path.join(path, entrypoint), "w") as f:
        f.write("print('hello world')")

    joined_path = os.path.join(path, entrypoint)
    out_path, out_entrypoint = _handle_artifact_entrypoint(joined_path)

    assert out_path == path, out_entrypoint == entrypoint


def test_configure_job_builder():
    dir = tempfile.TemporaryDirectory().name
    job_source = "repo"

    builder = _configure_job_builder(dir, job_source)
    assert isinstance(builder, JobBuilder)
    assert builder._config == {}
    assert builder._summary == {}
    assert builder._settings.get("files_dir") == dir
    assert builder._settings.get("job_source") == job_source


def test_make_code_artifact_name():
    name = "karen"

    assert make_code_artifact_name("./test", name) == f"code-{name}"
    assert make_code_artifact_name("./test", None) == f"code-test"
    assert make_code_artifact_name("test", None) == f"code-test"
    assert make_code_artifact_name("/test", None) == f"code-test"
    assert make_code_artifact_name("/test/", None) == f"code-test"
    assert make_code_artifact_name("./test/", None) == f"code-test"

    assert make_code_artifact_name("/test/dir", None) == f"code-test_dir"
    assert make_code_artifact_name("./test/dir/", None) == f"code-test_dir"


def test_dump_metadata_and_requirements():
    path = tempfile.TemporaryDirectory().name
    metadata = {"testing": "123"}
    requirements = ["wandb", "optuna"]

    dump_metadata_and_requirements(path, metadata, requirements)

    assert os.path.exists(os.path.join(path, "requirements.txt"))
    assert os.path.exists(os.path.join(path, "wandb-metadata.json"))

    with open(os.path.join(path, "requirements.txt"), "r") as f:
        assert f.read().strip().splitlines() == requirements

    m = json.load(open(os.path.join(path, "wandb-metadata.json"), "r"))
    assert metadata == m
