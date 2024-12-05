import json
import os
from unittest import mock

import pytest
import wandb
from wandb.errors import CommError, UsageError


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
