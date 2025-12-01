import pathlib
import subprocess


def test_flow_decoboth(wandb_backend_spy):
    """Test that the flow_decoboth.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_decoboth.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 4
        for run_id in run_ids:
            config = snapshot.config(run_id=run_id)
            assert config["seed"]["value"] == 1337
            assert config["test_size"]["value"] == 0.2
            assert config["raw_data"]["value"] == str(
                pathlib.Path(__file__).parent / "wine.csv"
            )

            telemetry = snapshot.telemetry(run_id=run_id)
            assert 13 in telemetry["1"]  # imports metaflow
            assert 11 in telemetry["3"]  # feature metaflow

            exit_code = snapshot.exit_code(run_id=run_id)
            assert exit_code == 0


def test_flow_decoclass(wandb_backend_spy):
    """Test that the flow_decoclass.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_decoclass.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 4
        for run_id in run_ids:
            config = snapshot.config(run_id=run_id)
            assert config["seed"]["value"] == 1337
            assert config["test_size"]["value"] == 0.2
            assert config["raw_data"]["value"] == str(
                pathlib.Path(__file__).parent / "wine.csv"
            )

            telemetry = snapshot.telemetry(run_id=run_id)
            assert 13 in telemetry["1"]  # imports metaflow
            assert 11 in telemetry["3"]  # feature metaflow

            exit_code = snapshot.exit_code(run_id=run_id)
            assert exit_code == 0


def test_flow_decostep(wandb_backend_spy):
    """Test that the flow_decostep.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_decostep.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 4
        for run_id in run_ids:
            config = snapshot.config(run_id=run_id)
            assert config["seed"]["value"] == 1337
            assert config["test_size"]["value"] == 0.2
            assert config["raw_data"]["value"] == str(
                pathlib.Path(__file__).parent / "wine.csv"
            )

            telemetry = snapshot.telemetry(run_id=run_id)
            assert 13 in telemetry["1"]  # imports metaflow
            assert 11 in telemetry["3"]  # feature metaflow

            exit_code = snapshot.exit_code(run_id=run_id)
            assert exit_code == 0


def test_flow_foreach(wandb_backend_spy):
    """Test that the flow_foreach.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_foreach.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 6
        for run_id in run_ids:
            config = snapshot.config(run_id=run_id)
            assert config["seed"]["value"] == 1337
            assert config["test_size"]["value"] == 0.2
            assert config["raw_data"]["value"] == str(
                pathlib.Path(__file__).parent / "wine.csv"
            )

            telemetry = snapshot.telemetry(run_id=run_id)
            assert 13 in telemetry["1"]  # imports metaflow
            assert 11 in telemetry["3"]  # feature metaflow

            exit_code = snapshot.exit_code(run_id=run_id)
            assert exit_code == 0


def test_flow_pytorch(wandb_backend_spy):
    """Test that the flow_pytorch.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_pytorch.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 5
        for run_id in run_ids:
            config = snapshot.config(run_id=run_id)
            assert config["batch_size"]["value"] == 64
            assert config["test_batch_size"]["value"] == 1000
            assert config["epochs"]["value"] == 1
            assert config["lr"]["value"] == 1.0
            assert config["gamma"]["value"] == 0.7
            assert not config["no_cuda"]["value"]
            assert config["seed"]["value"] == 1
            assert config["log_interval"]["value"] == 10
            assert not config["save_model"]["value"]

            telemetry = snapshot.telemetry(run_id=run_id)
            assert 13 in telemetry["1"]  # imports metaflow
            assert 11 in telemetry["3"]  # feature metaflow

            exit_code = snapshot.exit_code(run_id=run_id)
            assert exit_code == 0
