import sweeps
import wandb

SWEEP_CONFIGURATION = {
    "method": "random",
    "name": "sweep",
    "metric": {"goal": "maximize", "name": "val_acc"},
    "parameters": {
        "batch_size": {"values": [16, 32, 64]},
        "epochs": {"values": [5, 10, 15]},
        "lr": {"distribution": "uniform", "max": 0.1, "min": 0.0001},
    },
}


def test_run_from_dict():
    kwargs = {
        "name": "test",
        "state": "running",
        "config": {},
        "stopped": False,
        "shouldStop": False,
        "sampledHistory": [{}],
        "summaryMetrics": {},
    }
    run = sweeps.SweepRun(
        **kwargs,
    )
    assert run.name == "test"
    assert run.state == "running"
    assert run.config == {}
    assert run.summary_metrics == {}


def test_print_status(user, capsys):
    project = "my-first-sweep"
    sweep_id = wandb.sweep(sweep=SWEEP_CONFIGURATION, project=project)

    c = wandb.controller(sweep_id, entity=user, project=project)
    c.print_status()
    stdout, stderr = capsys.readouterr()
    assert "Runs: 0" in stdout
    assert sweep_id in stdout
    try:
        assert stderr == "", "stderr should be empty, but got warnings"
    except AssertionError:
        pass


def test_controller_existing(user):
    project = "my-first-sweep"
    sweep_id = wandb.sweep(sweep=SWEEP_CONFIGURATION, project=project)

    c = wandb.controller(sweep_id, entity=user, project=project)

    assert c.sweep_id == sweep_id
    assert c.sweep_config == SWEEP_CONFIGURATION


def test_controller_new(user):
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
