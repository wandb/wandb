import json
import os
from unittest import mock

import pytest
import wandb
from wandb.errors import CommError, UsageError
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


def test_resume_allow_success(wandb_backend_spy):
    with wandb.init() as run:
        run.log({"acc": 10}, step=15, commit=True)
    with wandb.init(resume="allow", id=run.id) as run:
        run.log({"acc": 10})

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert history[0]["_step"] == 15
        assert history[1]["_step"] == 16


def test_resume_never_failure(user):
    run = wandb.init(project="project")
    run_id = run.id
    run.finish()

    with pytest.raises(UsageError):
        wandb.init(resume="never", id=run_id, project="project")


def test_resume_must_failure(user):
    with pytest.raises(UsageError):
        wandb.init(resume="must", project="project")


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


def test_reinit_existing_run_with_reinit_true():
    """Test that reinit with an existing run returns a new run."""
    original_run = wandb.init(mode="offline")
    new_run = wandb.init(mode="offline", reinit=True)
    assert new_run != original_run


def test_reinit_existing_run_with_reinit_false():
    """Test that reinit with a run active returns the same run."""
    original_run = wandb.init(mode="offline")
    new_run = wandb.init(mode="offline", reinit=False)
    assert new_run == original_run


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


@pytest.mark.wandb_core_only
def test_shared_mode_x_label(wandb_backend_spy):
    """Test that reinit with a run active returns the same run."""
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
