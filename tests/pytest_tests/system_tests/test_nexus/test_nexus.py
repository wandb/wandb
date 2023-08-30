import pytest
from wandb.errors import CommError


def test_wandb_init(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log({"nexus": 1337})
        run.finish()
    history = relay.context.get_run_history(run.id)
    assert history["nexus"][0] == 1337


# TODO: this is just a smoke test to make sure we don't break offline mode
# remove it when we enable all the tests for nexus
def test_wandb_init_offline(relay_server, wandb_init):
    with relay_server():
        run = wandb_init(settings={"mode": "offline"})
        run.log({"nexus": 1337})
        run.finish()


def test_upsert_bucket_409(
    wandb_init,
    relay_server,
    inject_graphql_response,
):
    def custom_match_fn(self, other):  # noqa
        request_body = other.__dict__.get("body") or b"{}"
        return b"mutation UpsertBucket" in request_body

    inject_response = inject_graphql_response(
        body="GOT ME A 409",
        status=409,
        custom_match_fn=custom_match_fn,
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
    def custom_match_fn(self, other):  # noqa
        request_body = other.__dict__.get("body") or b"{}"
        return b"mutation UpsertBucket" in request_body

    inject_response = inject_graphql_response(
        body="GOT ME A 410",
        status=410,
        custom_match_fn=custom_match_fn,
        application_pattern="12",  # apply once and stop
    )
    # we do not retry 410s on upsert bucket mutations, so this should fail
    with relay_server(inject=[inject_response]):
        with pytest.raises(CommError):
            wandb_init()
