import pathlib
import subprocess

import pytest


@pytest.fixture
def create_artifact_spy(wandb_backend_spy):
    """A spy for CreateArtifact GQL operations."""
    gql = wandb_backend_spy.gql
    create_artifact_spy = gql.Capture()
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="CreateArtifact"),
        create_artifact_spy,
    )
    return create_artifact_spy


@pytest.fixture
def uploaded_artifact_hashes(create_artifact_spy):
    """Returns a map from uploaded artifact names to their digests."""

    def impl():
        hashes = {}

        for req in create_artifact_spy.requests:
            input = req.variables["input"]
            name = input["artifactCollectionName"]
            digest = input["digest"]
            hashes[name] = digest

        return hashes

    return impl


def test_flow_decoboth(wandb_backend_spy, uploaded_artifact_hashes):
    """Test that the flow_decoboth.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_decoboth.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    assert uploaded_artifact_hashes() == {
        "X_test": "74942b2c35708fb73a2e6ce602654080",
        "X_train": "5968b81781c14566d792c7a3e8247272",
        "raw_df": "bdc739f8da81537adb78ec69bf3dc3d0",
        "y_test": "dbbe2fb08c2b033e2e4949110dafd311",
        "y_train": "8feddd058760d5fd421c8483b0ed380f",
    }

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


def test_flow_decoclass(wandb_backend_spy, uploaded_artifact_hashes):
    """Test that the flow_decoclass.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_decoclass.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    assert uploaded_artifact_hashes() == {
        "X_test": "74942b2c35708fb73a2e6ce602654080",
        "X_train": "5968b81781c14566d792c7a3e8247272",
        "clf": "c941a43e8a5edc64683dc30a55a10a82",
        "preds": "95b8a4f5b1b7869d44df0093315c1914",
        "raw_df": "bdc739f8da81537adb78ec69bf3dc3d0",
        "y_test": "dbbe2fb08c2b033e2e4949110dafd311",
        "y_train": "8feddd058760d5fd421c8483b0ed380f",
    }

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


def test_flow_decostep(wandb_backend_spy, uploaded_artifact_hashes):
    """Test that the flow_decostep.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_decostep.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    assert uploaded_artifact_hashes() == {
        "raw_df": "bdc739f8da81537adb78ec69bf3dc3d0",
        "X_train": "5968b81781c14566d792c7a3e8247272",
        "X_test": "74942b2c35708fb73a2e6ce602654080",
        "y_train": "8feddd058760d5fd421c8483b0ed380f",
        "y_test": "dbbe2fb08c2b033e2e4949110dafd311",
    }

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


def test_flow_foreach(wandb_backend_spy, uploaded_artifact_hashes):
    """Test that the flow_foreach.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_foreach.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    assert uploaded_artifact_hashes() == {
        "X_test": "74942b2c35708fb73a2e6ce602654080",
        "X_train": "5968b81781c14566d792c7a3e8247272",
        "y_test": "dbbe2fb08c2b033e2e4949110dafd311",
        "y_train": "8feddd058760d5fd421c8483b0ed380f",
    }

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


def test_flow_pytorch(wandb_backend_spy, uploaded_artifact_hashes):
    """Test that the flow_pytorch.py script runs correctly."""
    script_path = pathlib.Path(__file__).parent / "flow_pytorch.py"
    subprocess.check_call(["python", str(script_path), "--no-pylint", "run"])

    assert uploaded_artifact_hashes() == {
        "mnist_dir": "64e7c61456b10382e2f3b571ac24b659",
    }

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
