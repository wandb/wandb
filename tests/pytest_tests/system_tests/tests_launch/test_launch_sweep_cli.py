import json
import subprocess
from typing import List

import pytest
import wandb
from wandb.apis.internal import InternalApi
from wandb.apis.public import Api
from wandb.sdk.launch.utils import LAUNCH_DEFAULT_PROJECT


def _run_cmd(cmd: List[str], assert_str: str) -> None:
    """Helper for asserting a statement is in logs."""
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    assert assert_str in out.decode("utf-8")


def test_launch_sweep_param_validation(user):
    base = ["wandb", "launch-sweep"]
    _run_cmd(base, "Usage: wandb launch-sweep [OPTIONS]")

    err_msg = "One of 'sweep_config' or 'resume_id' required"
    _run_cmd(base + ["-q", "q"], err_msg)

    err_msg = "Launch-sweeps require setting a 'queue'"
    _run_cmd(base + ["-sc", "s", "-e", "q"], err_msg)

    err_msg = "A project must be configured when using launch"
    _run_cmd(base + ["-sc", "c", "-q", "q", "-e", user], err_msg)

    base += ["-q", "q", "-e", user, "-p", "p"]
    err_msg = "Could not find sweep"
    with pytest.raises(subprocess.CalledProcessError):
        _run_cmd(base + ["-r", "id"], err_msg)

    config = {
        "method": "grid",
        "parameters": {"parameter1": {"values": [1, 2, 3]}},
    }
    with open("s.yaml", "w") as f:
        json.dump(config, f)

    err_msg = "No 'job' nor 'image_uri' found in sweep config"
    _run_cmd(base + ["-sc", "s.yaml"], err_msg)

    config["job"] = "job123"
    config["image_uri"] = "fake-image:latest"
    with open("s.yaml", "w") as f:
        json.dump(config, f)

    err_msg = "Sweep has both 'job' and 'image_uri'"
    _run_cmd(base + ["-sc", "s.yaml"], err_msg)

    del config["job"]
    with open("s.yaml", "w") as f:
        json.dump(config, f)

    # this tries to upsert into a non-existent project, because no error
    with pytest.raises(subprocess.CalledProcessError):
        _run_cmd(base + ["-sc", "s.yaml"], "")


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

    with open("sweep-config.yaml", "w") as f:
        json.dump(
            {
                "method": "grid",
                "image_uri": image_uri,
                "parameters": {"parameter1": {"values": [1, 2, 3]}},
            },
            f,
        )

    out = subprocess.check_output(
        [
            "wandb",
            "launch-sweep",
            "--sweep_config",
            "sweep-config.yaml",
            "-e",
            user,
            "-p",
            LAUNCH_DEFAULT_PROJECT,
            "-q",
            queue,
            "--launch_config",
            json.dumps(launch_config),
        ],
        stderr=subprocess.STDOUT,
    )

    assert "Scheduler added to launch queue (test)" in out.decode("utf-8")


@pytest.mark.parametrize(
    "image_uri,launch_config,job",
    [
        (None, {}, None),
        ("", {}, None),
        ("testing111", {"scheduler": {}}, "job123:v1"),
    ],
    ids=[
        "None, empty, None",
        "empty, None, None",
        "image + job",
    ],
)
def test_launch_sweep_launch_error(user, image_uri, launch_config, job):
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

    if not res or res.get("success") is not True:
        raise Exception("create queue" + str(res))

    with open("sweep-config.yaml", "w") as f:
        json.dump(
            {
                "job": job,
                "image_uri": image_uri,
                "method": "grid",
                "parameters": {"parameter1": {"values": [1, 2, 3]}},
            },
            f,
        )

    out = subprocess.check_output(
        [
            "wandb",
            "launch-sweep",
            "--sweep_config",
            "sweep-config.yaml",
            "-e",
            user,
            "-p",
            LAUNCH_DEFAULT_PROJECT,
            "-q",
            queue,
            "--launch_config",
            json.dumps(launch_config),
        ],
        stderr=subprocess.STDOUT,
    )

    if job:
        assert "Sweep has both 'job' and 'image_uri'" in out.decode("utf-8")
    else:
        assert "No 'job' nor 'image_uri' found in sweep config" in out.decode("utf-8")


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

    sweep_config = {
        "job": None,
        "method": "grid",
        "image_uri": "test-image:latest",
        "parameters": {"parameter1": {"values": [1, 2, 3]}},
    }

    with open("sweep-config.yaml", "w") as f:
        json.dump(sweep_config, f)

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
            "-q",
            "queue",
        ],
        stderr=subprocess.STDOUT,
    )
    assert "Scheduler added to launch queue (queue)" in out.decode("utf-8")
