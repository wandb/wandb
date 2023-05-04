import json
import subprocess
from typing import List

import pytest
import wandb
from wandb.apis.internal import InternalApi
from wandb.apis.public import Api
from wandb.sdk.launch.utils import LAUNCH_DEFAULT_PROJECT


def _run_cmd_check_msg(cmd: List[str], assert_str: str) -> None:
    """Helper for asserting a statement is in logs."""
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    assert assert_str in out.decode("utf-8")


def test_launch_sweep_param_validation(user, wandb_init):
    # make a job artifact for testing
    run = wandb_init()
    job_artifact = run._log_job_artifact_with_image("ljadnfakehbbr", args=[])
    job_name = job_artifact.wait().name
    run.finish()

    base = ["wandb", "launch-sweep"]
    _run_cmd_check_msg(base, "Usage: wandb launch-sweep [OPTIONS]")

    err_msg = "'config' and/or 'resume_id' required"
    _run_cmd_check_msg(base + ["-q", "q"], err_msg)

    base += ["-e", user, "-p", "p"]
    err_msg = "Could not find sweep"
    with pytest.raises(subprocess.CalledProcessError):
        _run_cmd_check_msg(base + ["-r", "id", "-q", "q"], err_msg)

    config = {
        "method": "grid",
        "parameters": {"parameter1": {"values": [1, 2, 3]}},
        "launch": {"queue": "q"},
    }
    json.dump(config, open("s.yaml", "w"))

    err_msg = "No 'job' nor 'image_uri' top-level key found in sweep config, exactly one is required for a launch-sweep"
    _run_cmd_check_msg(base + ["s.yaml"], err_msg)

    del config["launch"]["queue"]
    config["job"] = job_name
    json.dump(config, open("s.yaml", "w"))

    err_msg = "Launch-sweeps require setting a 'queue', use --queue option or a 'queue' key in the 'launch' section in the config"
    _run_cmd_check_msg(base + ["s.yaml", "-e", "e"], err_msg)

    base += ["-q", "q"]

    config["image_uri"] = "fake-image:latest"
    json.dump(config, open("s.yaml", "w"))

    err_msg = "Sweep config has both 'job' and 'image_uri' but a launch-sweep can use only one"
    _run_cmd_check_msg(base + ["s.yaml"], err_msg)

    del config["job"]
    json.dump(config, open("s.yaml", "w"))

    # this tries to upsert into a non-existent project, because no error
    with pytest.raises(subprocess.CalledProcessError):
        _run_cmd_check_msg(base + ["s.yaml"], "")

    with pytest.raises(subprocess.CalledProcessError):
        _run_cmd_check_msg(base + ["s123.yaml"], "Invalid value for '[CONFIG]'")


@pytest.mark.parametrize(
    "image_uri,launch_config",
    [
        ("testing111", {}),
        ("testing222", {"scheduler": {"num_workers": 5}}),
        ("testing222", {"scheduler": {"num_workers": "5"}}),
    ],
    ids=[
        "working",
        "num-workers-int",
        "num-workers-str",
    ],
)
def test_launch_sweep_launch_uri(user, image_uri, launch_config):
    queue = "test"
    api = InternalApi()
    public_api = Api()
    public_api.create_project(LAUNCH_DEFAULT_PROJECT, user)

    # make launch project queue
    res = api.create_run_queue(
        entity=user,
        project=LAUNCH_DEFAULT_PROJECT,
        queue_name=queue,
        access="USER",
    )

    if res.get("success") is not True:
        raise Exception("create queue" + str(res))

    sweep_config = {
        "method": "grid",
        "image_uri": image_uri,
        "parameters": {"parameter1": {"values": [1, 2, 3]}},
    }
    sweep_config.update(**launch_config)

    with open("sweep-config.yaml", "w") as f:
        json.dump(sweep_config, f)

    out = subprocess.check_output(
        [
            "wandb",
            "launch-sweep",
            "sweep-config.yaml",
            "-e",
            user,
            "-p",
            LAUNCH_DEFAULT_PROJECT,
            "-q",
            queue,
        ],
        stderr=subprocess.STDOUT,
    )

    assert "Scheduler added to launch queue (test)" in out.decode("utf-8")


def test_launch_sweep_launch_resume(user):
    api = InternalApi()
    public_api = Api()
    public_api.create_project(LAUNCH_DEFAULT_PROJECT, user)

    # make launch project queue
    res = api.create_run_queue(
        entity=user,
        project=LAUNCH_DEFAULT_PROJECT,
        queue_name="queue",
        access="USER",
    )

    if res.get("success") is not True:
        raise Exception("create queue" + str(res))

    with pytest.raises(subprocess.CalledProcessError):
        out = subprocess.check_output(
            [
                "wandb",
                "launch-sweep",
                "--resume_id",
                "bogussweepid",
                "-e",
                user,
                "-p",
                LAUNCH_DEFAULT_PROJECT,
                "-q",
                "queue",
            ],
            stderr=subprocess.STDOUT,
        )
        assert "Launch-sweeps require setting a 'queue'" in out.decode("utf-8")

    sweep_config = {
        "job": None,
        "method": "grid",
        "image_uri": "test-image:latest",
        "parameters": {"parameter1": {"values": [1, 2, 3]}},
    }
    with open("sweep-config.yaml", "w") as f:
        json.dump(sweep_config, f)

    # Entity, project, and sweep
    sweep_id = wandb.sweep(sweep_config, entity=user, project=LAUNCH_DEFAULT_PROJECT)

    # no queue
    out = subprocess.check_output(
        [
            "wandb",
            "launch-sweep",
            "--resume_id",
            sweep_id,
            "-e",
            user,
            "-p",
            LAUNCH_DEFAULT_PROJECT,
        ],
        stderr=subprocess.STDOUT,
    )
    assert "Launch-sweeps require setting a 'queue'" in out.decode("utf-8")

    config = {"launch": {"queue": "queue"}}
    json.dump(config, open("s.yaml", "w"))

    out = subprocess.check_output(
        [
            "wandb",
            "launch-sweep",
            "s.yaml",
            "--resume_id",
            sweep_id,
            "-e",
            user,
            "-p",
            LAUNCH_DEFAULT_PROJECT,
        ],
        stderr=subprocess.STDOUT,
    )
    assert "Scheduler added to launch queue (queue)" in out.decode("utf-8")
