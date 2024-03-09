import json
import re
from unittest import mock

import pytest
from wandb.sdk.internal import job_builder


def test_run_use_job_env_var(runner, relay_server, test_settings, user, wandb_init):
    art_name = "job-my-test-image"
    artifact_name = f"{user}/uncategorized/{art_name}"
    artifact_env = json.dumps({"_wandb_job": f"{artifact_name}:latest"})
    with runner.isolated_filesystem(), mock.patch.dict(
        "os.environ", WANDB_ARTIFACTS=artifact_env
    ):
        artifact = job_builder.JobArtifact(name=art_name)
        filename = "file1.txt"
        with open(filename, "w") as fp:
            fp.write("hello!")
        artifact.add_file(filename)
        with wandb_init(user) as run:
            run.log_artifact(artifact)
            artifact.wait()
        with relay_server() as relay:
            with wandb_init(user, settings=test_settings({"launch": True})) as run:
                run.log({"x": 2})
            use_count = 0
            for data in relay.context.raw_data:
                assert "mutation CreateArtifact(" not in data.get("request", {}).get(
                    "query", ""
                )
                if "mutation UseArtifact(" in data.get("request", {}).get("query", ""):
                    use_count += 1
        assert use_count == 1


@pytest.mark.wandb_core_failure(feature="launch")
def test_footer_job_output(wandb_init, capsys, monkeypatch):
    """Test that footer includes job info when a job is created."""
    monkeypatch.setenv("WANDB_DOCKER", "hello-world")  # Needed to trigger job creation.
    run = wandb_init()
    run.log({"a": 1})
    run.finish()
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    for line in lines:
        if re.search(
            r"View job at http://localhost:8080/user-\w+-\w+/uncategorized/jobs/[\w=]+/version_details/v0",
            line,
        ):
            break
    else:
        raise AssertionError(f"Job URL not found in footer: {captured.err}")
