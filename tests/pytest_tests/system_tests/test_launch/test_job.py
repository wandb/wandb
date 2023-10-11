import json
import os
import tempfile
from unittest import mock

import pytest
from wandb.apis.public import Api as PublicApi
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.create_job import _create_job
from wandb.sdk.launch.github_reference import GitHubReference


def test_job_call(relay_server, user, wandb_init, test_settings):
    proj = "TEST_PROJECT"
    queue = "TEST_QUEUE"
    public_api = PublicApi()
    internal_api = InternalApi()
    settings = test_settings({"project": proj})

    with relay_server():
        run = wandb_init(settings=settings)

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
        assert queued_run.container_job is True

        rqi = internal_api.pop_from_run_queue(queue, user, proj)

        assert rqi["runSpec"]["job"].split("/")[-1] == f"job-{docker_image}:v0"
        assert rqi["runSpec"]["project"] == proj
        run.finish()


def test_create_job_artifact(runner, user, wandb_init, test_settings):
    proj = "test-p"
    settings = test_settings({"project": proj})

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

    artifact, action, aliases = _create_job(
        api=internal_api,
        path=source_dir,
        project=proj,
        entity=user,
        job_type="code",
        description="This is a description",
        entrypoint="test.py",
        name="test-job-9999",
        runtime="3.8.9",  # micro will get stripped
    )

    assert isinstance(artifact, Artifact)
    assert artifact.name == "test-job-9999:v0"
    assert action == "Created"
    assert aliases == ["latest"]

    job_v0 = public_api.job(f"{user}/{proj}/{artifact.name}")

    assert job_v0._partial
    assert job_v0._job_info["runtime"] == "3.8"
    assert job_v0._job_info["_version"] == "v0"
    assert job_v0._job_info["source"]["entrypoint"] == ["python3.8", "test.py"]
    assert job_v0._job_info["source"]["notebook"] is False

    # Now use artifact as input, assert it gets upgraded
    artifact_env = json.dumps({"_wandb_job": artifact.name})
    with runner.isolated_filesystem(), mock.patch.dict(
        "os.environ", WANDB_ARTIFACTS=artifact_env
    ):
        settings.update(
            {
                "job_source": "artifact",
                "launch": True,
            }
        )
        run2 = wandb_init(settings=settings, config={"input1": 1})
        run2.log({"x": 2})
        run2.finish()

    # now get the job, the version should be v1
    v1_job = artifact.name.split(":")[0] + ":v1"
    job = public_api.job(f"{user}/{proj}/{v1_job}")

    assert job

    # assert updates to partial, and input/output types
    assert not job._partial
    assert (
        str(job._output_types)
        == "{'x': Number, '_timestamp': Number, '_runtime': Number, '_step': Number}"
    )
    assert str(job._input_types) == "{'input1': Number}"


def test_create_git_job(runner, user, wandb_init, test_settings, monkeypatch):
    proj = "test-p99999"
    settings = test_settings({"project": proj})

    internal_api = InternalApi()
    public_api = PublicApi()

    path = "https://username:pword@github.com/wandb/mock-examples-123/blob/commit/path/requirements.txt"

    def mock_fetch_repo(self, dst_dir):
        # mock dumping a file to the local clone of the repo
        os.makedirs(os.path.join(dst_dir, "commit/path/"), exist_ok=True)
        with open(os.path.join(dst_dir, "commit/path/requirements.txt"), "w") as f:
            f.write("wandb\n")

        with open(os.path.join(dst_dir, "commit/path/runtime.txt"), "w") as f:
            f.write("3.8.9\n")

        with open(os.path.join(dst_dir, "commit/path/main.py"), "w") as f:
            f.write("print('hello world')")

        self.commit_hash = "1234567890"
        self._update_path(dst_dir)

    monkeypatch.setattr(GitHubReference, "fetch", mock_fetch_repo)

    artifact, action, aliases = _create_job(
        api=internal_api,
        path=path,
        entrypoint="main.py",
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

    assert job_v0._partial
    assert job_v0._job_info["runtime"] == "3.8"
    assert job_v0._job_info["_version"] == "v0"
    assert job_v0._job_info["source"]["entrypoint"] == [
        "python3.8",
        "commit/path/main.py",
    ]
    assert job_v0._job_info["source"]["notebook"] is False

    # Now use artifact as input, assert it gets upgraded
    artifact_env = json.dumps({"_wandb_job": artifact.name})
    with runner.isolated_filesystem(), mock.patch.dict(
        "os.environ", WANDB_ARTIFACTS=artifact_env
    ):
        settings.update(
            {
                "job_source": "repo",
                "launch": True,
            }
        )
        run2 = wandb_init(settings=settings, config={"input1": 1})
        run2.log({"x": 2})
        run2.finish()

    # now get the job, the version should be v1
    v1_job = artifact.name.split(":")[0] + ":v1"
    job = public_api.job(f"{user}/{proj}/{v1_job}")

    assert job

    # assert updates to partial, and input/output types
    assert not job._partial
    assert (
        str(job._output_types)
        == "{'x': Number, '_timestamp': Number, '_runtime': Number, '_step': Number}"
    )
    assert str(job._input_types) == "{'input1': Number}"


@pytest.mark.parametrize(
    "image_name",
    [
        "test/docker-image-path:alias1",
        "port:5000/test/docker-image-path:alias1",
        "port:5000/test/docker-image-path",
        "port:5000:1000/1000/test/docker-image-path:alias1",
    ],
)
def test_create_job_image(user, wandb_init, test_settings, image_name):
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
    assert job._partial
