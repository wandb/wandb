import wandb
from wandb import sweeps
import sys
import pytest


pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 5), reason="wandb_controller doesn't support py2"
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


def test_print_status(mock_server, capsys):
    c = wandb.controller("test", entity="test", project="test")
    c.print_status()
    stdout, stderr = capsys.readouterr()
    assert stdout == "Sweep: fun-sweep-10 (unknown) | Runs: 1 (Running: 1)\n"
    assert stderr == ""


def test_controller_existing(mock_server):
    c = wandb.controller("test", entity="test", project="test")
    assert c.sweep_id == "test"
    assert c.sweep_config == {"metric": {"name": "loss", "value": "minimize"}}


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
            "param1": {"values": [1, 2, 3]},
            "param2": {"values": [1, 2, 3]},
        },
        "program": "train-dummy.py",
    }


# TODO: More controller tests!
