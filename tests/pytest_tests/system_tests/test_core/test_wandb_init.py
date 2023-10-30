import pytest
from wandb.errors import CommError


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


@pytest.mark.skip(reason="we should handle such cases gracefully")
@pytest.mark.nexus_failure(feature="error_handling")  # now we just panic
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
        with pytest.raises(CommError):
            wandb_init()


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
