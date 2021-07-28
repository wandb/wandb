import wandb
import sys
import platform
import pytest
from wandb import sweeps_engine


pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 5), reason="wandb_controller doesn't support py2"
)


def test_run_from_dict():

    run = sweeps_engine.SweepRun(
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


def test_print_status(mock_server, capsys):
    c = wandb.controller("test", entity="test", project="test")
    c.print_status()
    stdout, stderr = capsys.readouterr()
    assert stdout == "Sweep: fun-sweep-10 (random) | Runs: 1 (Running: 1)\n"
    # For some reason, the windows and mac tests are failing in CI
    # as there are write permissions warnings.
    if platform.system() != "Windows" and platform.system() != "Darwin":
        assert stderr == ""


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
