import pathlib

import pytest


@pytest.mark.wandb_core_only
def test_strategy_ddp_spawn(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "strategy_ddp_spawn.py"
        execute_script(script_path)

    assert len(relay.context.get_run_ids()) == 1
    run_id = relay.context.get_run_ids()[0]

    history = relay.context.get_run_history(run_id)
    assert history["trainer/global_step"][30] == 1549
    config = relay.context.get_run_config(run_id)
    assert config["some_hparam"]["value"] == "Logged Before Trainer starts DDP"
    summary = relay.context.get_run_summary(run_id)
    assert summary["epoch"] == 0
    assert summary["loss"] >= 0
    assert summary["trainer/global_step"] == 0
    assert summary["fake_test_acc"] >= 0
    telemetry = relay.context.get_run_telemetry(run_id)
    assert 106 in telemetry["2"]  # import=lightning


@pytest.mark.wandb_core_only
def test_strategy_ddp(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "strategy_ddp.py"
        execute_script(script_path)

    assert len(relay.context.get_run_ids()) == 1
    run_id = relay.context.get_run_ids()[0]

    history = relay.context.get_run_history(run_id)
    assert history["trainer/global_step"][30] == 1549
    config = relay.context.get_run_config(run_id)
    assert config["some_hparam"]["value"] == "Logged Before Trainer starts DDP"
    summary = relay.context.get_run_summary(run_id)
    assert summary["epoch"] == 1
    assert summary["loss"] >= 0
    assert summary["trainer/global_step"] == 1563
    assert summary["fake_test_acc"] >= 0
    telemetry = relay.context.get_run_telemetry(run_id)
    assert 106 in telemetry["2"]  # import=lightning
