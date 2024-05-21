import json
import os
import time
from unittest import mock

import pytest
from wandb.apis.public import Api
from wandb.errors import CommError, UsageError


def test_upsert_bucket_409(
    wandb_init,
    relay_server,
    inject_graphql_response,
):
    """Test that we retry upsert bucket mutations on 409s."""
    inject_response = inject_graphql_response(
        body="GOT ME A 409",
        status=409,
        query_match_fn=lambda query, variables: "mutation UpsertBucket" in query,
        application_pattern="12",  # apply once and stop
    )
    # we'll retry once and succeed
    with relay_server(inject=[inject_response]):
        run = wandb_init()

    run.finish()


def test_upsert_bucket_410(
    wandb_init,
    relay_server,
    inject_graphql_response,
):
    """Test that we do not retry upsert bucket mutations on 410s."""
    inject_response = inject_graphql_response(
        body="GOT ME A 410",
        status=410,
        query_match_fn=lambda query, variables: "mutation UpsertBucket" in query,
        application_pattern="12",  # apply once and stop
    )
    # we do not retry 410s on upsert bucket mutations, so this should fail
    with relay_server(inject=[inject_response]):
        with pytest.raises(CommError):
            wandb_init()


def test_gql_409(
    wandb_init,
    relay_server,
    inject_graphql_response,
):
    """Test that we retry upsert bucket mutations on 409s."""
    inject_response = inject_graphql_response(
        body="GOT ME A 409",
        status=409,
        query_match_fn=lambda query, variables: "mutation CreateRunFiles" in query,
        application_pattern="12",  # apply once and stop
    )
    # we do not retry 409s on queries, so this should fail
    with relay_server(inject=[inject_response]):
        run = wandb_init()
        run.finish()


def test_gql_410(
    wandb_init,
    test_settings,
    relay_server,
    inject_graphql_response,
):
    """Test that we do not retry upsert bucket mutations on 410s."""
    inject_response = inject_graphql_response(
        body="GOT ME A 410",
        status=410,
        query_match_fn=lambda query, variables: "mutation CreateRunFiles" in query,
        application_pattern="1112",  # apply thrice and stop
    )
    # we'll retry once and succeed
    with relay_server(inject=[inject_response]):
        run = wandb_init(settings=test_settings({"_graphql_retry_max": 4}))
        run.finish()


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

        # Wait for run metadata to finish uploading
        api = Api()
        api_run = api.run(f"{run.entity}/project/{run_id}")
        metadata = None
        tries = 0
        while metadata is None and tries < 5:
            metadata = api_run.metadata
            time.sleep(1)
        assert metadata is not None

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
