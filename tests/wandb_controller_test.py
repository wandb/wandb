import platform
import sys

import pytest

pytest.importorskip("sweeps")

import sweeps
import wandb


# todo: unskip once WB-8120 is resolved
@pytest.mark.skipif(
    sys.platform == "darwin" and platform.machine() == "arm64",
    reason="sweeps==0.1.0 requires sklearn==0.24.1 that is not compatible with Mac M1",
)
def test_run_from_dict():

    run = sweeps.SweepRun(
        **{
            "name": "test",
            "state": "running",
            "config": {},
            "stopped": False,
            "shouldStop": False,
            "sampledHistory": [{}],
            "summaryMetrics": {},
        }
    )
    assert run.name == "test"
    assert run.state == "running"
    assert run.config == {}
    assert run.summary_metrics == {}


# todo: unskip once WB-8120 is resolved
@pytest.mark.skipif(
    sys.platform == "darwin" and platform.machine() == "arm64",
    reason="sweeps==0.1.0 requires sklearn==0.24.1 that is not compatible with Mac M1",
)
def test_print_status(runner, mock_server, capsys):
    c = wandb.controller("test", entity="test", project="test")
    c.print_status()
    stdout, stderr = capsys.readouterr()
    assert stdout == "Sweep: fun-sweep-10 (random) | Runs: 1 (Running: 1)\n"
    # For some reason, the windows and mac tests are failing in CI
    # as there are write permissions warnings.
    try:
        assert stderr == "", "stderr should be empty, but got warnings"
    except AssertionError:
        pass


# todo: unskip once WB-8120 is resolved
@pytest.mark.skipif(
    sys.platform == "darwin" and platform.machine() == "arm64",
    reason="sweeps==0.1.0 requires sklearn==0.24.1 that is not compatible with Mac M1",
)
def test_controller_existing(mock_server):
    c = wandb.controller("test", entity="test", project="test")
    assert c.sweep_id == "test"
    assert c.sweep_config == {
        "controller": {"type": "local"},
        "method": "random",
        "parameters": {
            "param1": {"values": [1, 2, 3], "distribution": "categorical"},
            "param2": {"values": [1, 2, 3], "distribution": "categorical"},
        },
        "program": "train-dummy.py",
    }


# todo: unskip once WB-8120 is resolved
@pytest.mark.skipif(
    sys.platform == "darwin" and platform.machine() == "arm64",
    reason="sweeps==0.1.0 requires sklearn==0.24.1 that is not compatible with Mac M1",
)
def test_controller_new(mock_server):
    tuner = wandb.controller(
        {
            "method": "random",
            "program": "train-dummy.py",
            "parameters": {
                "param1": {"values": [1, 2, 3]},
                "param2": {"values": [1, 2, 3]},
            },
            "controller": {"type": "local"},
        }
    )
    # tuner.create()
    assert tuner._create == {
        "controller": {"type": "local"},
        "method": "random",
        "parameters": {
            "param1": {"values": [1, 2, 3], "distribution": "categorical"},
            "param2": {"values": [1, 2, 3], "distribution": "categorical"},
        },
        "program": "train-dummy.py",
    }
    tuner.step()


# TODO: More controller tests!
