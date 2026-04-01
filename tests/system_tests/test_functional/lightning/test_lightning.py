import pathlib


def test_strategy_ddp_spawn(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "strategy_ddp_spawn.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        history = snapshot.history(run_id=run_id)
        assert len(history) >= 1
        config = snapshot.config(run_id=run_id)
        assert config["some_hparam"]["value"] == "Logged Before Trainer starts DDP"
        summary = snapshot.summary(run_id=run_id)
        assert summary["fake_test_acc"] >= 0
        telemetry = snapshot.telemetry(run_id=run_id)
        assert 106 in telemetry["2"]  # import=lightning


def test_strategy_ddp(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "strategy_ddp.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        history = snapshot.history(run_id=run_id)
        assert len(history) >= 1
        config = snapshot.config(run_id=run_id)
        assert config["some_hparam"]["value"] == "Logged Before Trainer starts DDP"
        summary = snapshot.summary(run_id=run_id)
        assert summary["epoch"] == 1
        assert summary["fake_test_acc"] >= 0
        telemetry = snapshot.telemetry(run_id=run_id)
        assert 106 in telemetry["2"]  # import=lightning
