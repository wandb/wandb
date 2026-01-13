import json
import os
from unittest import mock

import pytest
import wandb
from wandb.errors import AuthenticationError, CommError
from wandb.sdk.lib import runid


def test_upsert_bucket_409(wandb_backend_spy):
    """Test that we retry upsert bucket mutations on 409s."""
    gql = wandb_backend_spy.gql
    responder = gql.once(content="", status=409)
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="UpsertBucket"),
        responder,
    )

    with wandb.init():
        pass

    assert responder.total_calls >= 2


def test_upsert_bucket_410(wandb_backend_spy):
    """Test that we do not retry upsert bucket mutations on 410s."""
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="UpsertBucket"),
        gql.once(content="", status=410),
    )

    with pytest.raises(CommError):
        wandb.init()


def test_gql_409(wandb_backend_spy):
    """Test that we do retry non-UpsertBucket GraphQL operations on 409s."""
    gql = wandb_backend_spy.gql
    responder = gql.once(content="", status=409)
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="CreateRunFiles"),
        responder,
    )

    with wandb.init():
        pass

    assert responder.total_calls >= 2


def test_gql_410(wandb_backend_spy):
    """Test that we do retry non-UpsertBucket GraphQL operations on 410s."""
    gql = wandb_backend_spy.gql
    responder = gql.once(content="", status=410)
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="CreateRunFiles"),
        responder,
    )

    with wandb.init():
        pass

    assert responder.total_calls >= 2


def test_send_wandb_config_start_time_on_init(wandb_backend_spy):
    with wandb.init() as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        config = snapshot.config(run_id=run.id)

        assert "_wandb" in config
        assert "value" in config["_wandb"]
        assert "t" in config["_wandb"]["value"]


def test_resume_auto_failure(user, tmp_path):
    # env vars have a higher priority than the BASE settings
    # so that if that is set (e.g. by some other test/fixture),
    # test_settings.wandb_dir != run_settings.wandb_dir
    # and this test will fail
    with mock.patch.dict(os.environ, {"WANDB_DIR": str(tmp_path.absolute())}):
        run = wandb.init(project="project", id="resume-me")
        run.finish()
        resume_fname = run._settings.resume_fname
        with open(resume_fname, "w") as f:
            f.write(json.dumps({"run_id": "resume-me"}))
        run = wandb.init(resume="auto", project="project")
        assert run.id == "resume-me"
        run.finish(exit_code=3)
        assert os.path.exists(resume_fname)


def test_init_param_telemetry(wandb_backend_spy):
    with wandb.init(
        name="my-test-run",
        id=runid.generate_id(),
        config={"a": 123},
        tags=["one", "two"],
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        features = snapshot.telemetry(run_id=run.id)["3"]
        assert 13 in features  # set_init_name
        assert 14 in features  # set_init_id
        assert 15 in features  # set_init_tags
        assert 16 in features  # set_init_config


def test_init_param_not_set_telemetry(wandb_backend_spy):
    with wandb.init() as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        features = snapshot.telemetry(run_id=run.id)["3"]
        assert 13 not in features  # set_init_name
        assert 14 not in features  # set_init_id
        assert 15 not in features  # set_init_tags
        assert 16 not in features  # set_init_config


def test_init_uses_given_api_key():
    api_key = "invalid-api-key"
    with pytest.raises(AuthenticationError, match=r"API key must have 40\+ characters"):
        wandb.init(settings=wandb.Settings(api_key=api_key))


def test_init_with_api_key_no_netrc(user, tmp_path, monkeypatch):
    netrc_path = str(tmp_path / "netrc")
    monkeypatch.setenv("NETRC", netrc_path)

    # No netrc before init
    assert not os.path.exists(netrc_path)

    # Explicitly pass the key
    with wandb.init(settings=wandb.Settings(api_key=user)):
        pass

    # No netrc after init
    assert not os.path.exists(netrc_path)


def test_shared_mode_x_label(user):
    _ = user  # Create a fake user on the backend server.

    with wandb.init() as run:
        assert run.settings.x_label is None

    with wandb.init(
        settings=wandb.Settings(
            mode="shared",
        )
    ) as run:
        assert run.settings.x_label is not None

    with wandb.init(
        settings=wandb.Settings(
            mode="shared",
            x_label="node-rank",
        )
    ) as run:
        assert run.settings.x_label == "node-rank"


@pytest.mark.parametrize("skip_transaction_log", [True, False])
def test_skip_transaction_log(user, skip_transaction_log):
    """Test that the skip transaction log setting works correctly.

    If skip_transaction_log is True, the transaction log file should not be created.
    If skip_transaction_log is False, the transaction log file should be created.
    """
    with wandb.init(
        settings={
            "x_skip_transaction_log": skip_transaction_log,
            "mode": "online",
        }
    ) as run:
        pass
    assert os.path.exists(run._settings.sync_file) == (not skip_transaction_log)


def test_skip_transaction_log_offline(user):
    """Test that skip transaction log is not allowed in offline mode."""
    with pytest.raises(ValueError):
        wandb.init(settings={"mode": "offline", "x_skip_transaction_log": True})
