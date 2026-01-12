from __future__ import annotations

import json
import os
import tempfile
from unittest import mock

import pytest
import wandb
from wandb.apis.internal import Api as InternalApi
from wandb.apis.public import Api as PublicApi
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.launch.create_job import _create_job
from wandb.sdk.launch.git_reference import GitReference


def test_job_call(user):
    proj = "TEST_PROJECT"
    queue = "TEST_QUEUE"
    public_api = PublicApi()
    internal_api = InternalApi()

    run = wandb.init(settings=wandb.Settings(project=proj))

    docker_image = "TEST_IMAGE"
    job_artifact = run._log_job_artifact_with_image(docker_image)
    job_name = job_artifact.wait().name
    job = public_api.job(f"{user}/{proj}/{job_name}")

    internal_api.create_run_queue(
        entity=user, project=proj, queue_name=queue, access="PROJECT"
    )

    queued_run = job.call(config={}, project=proj, queue=queue, project_queue=proj)

    assert queued_run.state == "pending"
    assert queued_run.entity == user
    assert queued_run.project == proj

    rqi = internal_api.pop_from_run_queue(queue, user, proj)

    assert rqi["runSpec"]["job"].split("/")[-1] == f"job-{docker_image}:v0"
    assert rqi["runSpec"]["project"] == proj
    run.finish()


def test_create_job_artifact(runner, user):
    """Test that non-core job creation produces a partial job as expected."""
    proj = "test-p"
    settings = wandb.Settings(project=proj)

    internal_api = InternalApi()
    public_api = PublicApi()

    # create code artifact dir
    source_dir = "./" + tempfile.TemporaryDirectory().name
    os.makedirs(source_dir)

    with open(f"{source_dir}/test.py", "w") as f:
        f.write("print('hello world')")

    # dump requirements.txt
    with open(f"{source_dir}/requirements.txt", "w") as f:
        f.write("wandb")

    os.makedirs(f"{source_dir}/wandb")
    with open(f"{source_dir}/wandb/debug.log", "w") as f:
        f.write("log text")

    artifact, action, aliases = _create_job(
        api=internal_api,
        path=source_dir,
        project=proj,
        entity=user,
        job_type="code",
        description="This is a description",
        entrypoint="python test.py",
        name="test-job-9999",
        runtime="3.8",  # micro will get stripped
        dockerfile="Dockerfile",
        build_context="src/",
    )

    assert isinstance(artifact, Artifact)
    assert artifact.file_count == 2
    assert artifact.name == "test-job-9999:v0"
    assert action == "Created"
    assert aliases == ["latest"]

    job_v0 = public_api.job(f"{user}/{proj}/{artifact.name}")

    assert "_partial" in job_v0._job_artifact.metadata
    assert job_v0._job_info["runtime"] == "3.8"
    assert job_v0._job_info["_version"] == "0.17.0"
    assert job_v0._job_info["source"]["entrypoint"] == ["python", "test.py"]
    assert job_v0._job_info["source"]["notebook"] is False

    # Now use artifact as input, assert it gets upgraded
    artifact_env = json.dumps({"_wandb_job": artifact.name})
    with (
        runner.isolated_filesystem(),
        mock.patch.dict("os.environ", WANDB_ARTIFACTS=artifact_env),
    ):
        settings.job_source = "artifact"
        settings.launch = True
        settings.disable_job_creation = False

        run2 = wandb.init(settings=settings, config={"input1": 1})
        run2.log({"x": 2})
        run2.finish()

    # now get the job, the version should be v1
    job = public_api.job(f"{user}/{proj}/{artifact.name}")

    assert job
    assert "_partial" not in job._job_artifact.metadata
    assert "input_types" in job._job_artifact.metadata
    assert "output_types" in job._job_artifact.metadata


def test_create_git_job(runner, user, monkeypatch):
    """This tests that a git job is created correctly, and that the job is upgraded correctly.

    Currently failing at the artifact creation stage with wandb-core. Appears to be an issue
    with the artifact saver that is only happening when running in CI.
    """
    proj = "test-p99999"
    settings = wandb.Settings(project=proj)

    internal_api = InternalApi()
    public_api = PublicApi()

    path = "https://username:pword@github.com/wandb/mock-examples-123/blob/commit/path/requirements.txt"

    def mock_fetch_repo(self, dst_dir):
        # mock dumping a file to the local clone of the repo
        os.makedirs(os.path.join(dst_dir, "commit/"), exist_ok=True)
        with open(os.path.join(dst_dir, "commit/requirements.txt"), "w") as f:
            f.write("wandb\n")

        with open(os.path.join(dst_dir, "commit/runtime.txt"), "w") as f:
            f.write("3.8.9\n")

        with open(os.path.join(dst_dir, "commit/main.py"), "w") as f:
            f.write("print('hello world')")

        self.commit_hash = "1234567890"
        self.path = "commit"

    monkeypatch.setattr(GitReference, "fetch", mock_fetch_repo)

    artifact, action, aliases = _create_job(
        api=internal_api,
        path=path,
        entrypoint="python main.py",
        project=proj,
        entity=user,
        job_type="git",
        description="This is a description",
        name="test-job-000000",
    )

    assert isinstance(artifact, Artifact)
    assert artifact.name == "test-job-000000:v0"
    assert action == "Created"
    assert aliases == ["latest"]

    job_v0 = public_api.job(f"{user}/{proj}/{artifact.name}")

    assert "_partial" in job_v0._job_artifact.metadata
    assert job_v0._job_info["runtime"] == "3.8"
    assert job_v0._job_info["_version"] == "v0"
    assert job_v0._job_info["source"]["entrypoint"] == [
        "python",
        "main.py",
    ]
    assert job_v0._job_info["source"]["notebook"] is False

    # Now use artifact as input, assert it gets upgraded
    artifact_env = json.dumps({"_wandb_job": artifact.name})
    with (
        runner.isolated_filesystem(),
        mock.patch.dict("os.environ", WANDB_ARTIFACTS=artifact_env),
    ):
        settings.job_source = "repo"
        settings.launch = True
        settings.disable_job_creation = False

        run2 = wandb.init(settings=settings, config={"input1": 1})
        run2.log({"x": 2})
        run2.finish()

    # now get the job again, the version should be the same
    job = public_api.job(f"{user}/{proj}/{artifact.name}")
    assert job

    # assert updates to partial, and input/output types
    assert "_partial" not in job._job_artifact.metadata
    assert "input_types" in job._job_artifact.metadata
    assert "output_types" in job._job_artifact.metadata


@pytest.mark.parametrize(
    "image_name",
    [
        "test/docker-image-path:alias1",
        "port:5000/test/docker-image-path:alias1",
        "port:5000/test/docker-image-path",
        "port:5000:1000/1000/test/docker-image-path:alias1",
    ],
)
def test_create_job_image(user, image_name):
    proj = "test-p1"

    internal_api = InternalApi()
    public_api = PublicApi()

    artifact, action, aliases = _create_job(
        api=internal_api,
        path=image_name,
        project=proj,
        entity=user,
        job_type="image",
        description="This is a description",
        name="test-job-1111",
    )

    assert isinstance(artifact, Artifact)
    assert artifact.name == "test-job-1111:v0"
    assert action == "Created"

    gold_aliases = ["latest"]
    if image_name[-1] == "1":
        gold_aliases = ["alias1", "latest"]

    assert aliases == gold_aliases

    job = public_api.job(f"{user}/{proj}/{artifact.name}")
    assert job
    assert "_partial" in job._job_artifact.metadata
