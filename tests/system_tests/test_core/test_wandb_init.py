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


def test_send_wandb_config_start_time_on_init(wandb_init, relay_server):
    with relay_server() as relay:
        run = wandb_init(project="test")
        run.finish()
        config = relay.context.config[run.id]
        assert config.get("_wandb", {}).get("value", {}).get("t") is not None


def test_resume_no_metadata(relay_server, wandb_init):
    run = wandb_init(project="test")
    run_id = run.id
    run.finish()

    with relay_server() as relay:
        run = wandb_init(resume="allow", id=run_id, project="test")
        run.finish()
        uploaded_files = relay.context.get_run_uploaded_files(run_id)

        assert "wandb-metadata.json" not in uploaded_files


def test_resume_allow_success(
    wandb_init,
    relay_server,
):
    with relay_server() as relay:
        run = wandb_init(project="project")
        run_id = run.id
        run.log({"acc": 10}, step=15, commit=True)
        run.finish()

        run = wandb_init(resume="allow", id=run_id, project="project")
        run.log({"acc": 10})
        run.finish()
        history = relay.context.get_run_history(run_id, include_private=True)
        assert len(history["_step"]) == 2 and history["_step"][1] == 16


def test_resume_never_failure(wandb_init):
    run = wandb_init(project="project")
    run_id = run.id
    run.finish()

    with pytest.raises(UsageError):
        wandb_init(resume="never", id=run_id, project="project")


def test_resume_must_failure(wandb_init):
    with pytest.raises(UsageError):
        wandb_init(resume="must", project="project")


def test_resume_auto_failure(wandb_init, tmp_path):
    # env vars have a higher priority than the BASE settings
    # so that if that is set (e.g. by some other test/fixture),
    # test_settings.wandb_dir != run_settings.wandb_dir
    # and this test will fail
    with mock.patch.dict(os.environ, {"WANDB_DIR": str(tmp_path.absolute())}):
        run = wandb_init(project="project", id="resume-me")
        run.finish()
        resume_fname = run._settings.resume_fname
        with open(resume_fname, "w") as f:
            f.write(json.dumps({"run_id": "resume-me"}))
        run = wandb_init(resume="auto", project="project")
        assert run.id == "resume-me"
        run.finish(exit_code=3)
        assert os.path.exists(resume_fname)
