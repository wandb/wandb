from typing import TYPE_CHECKING, Callable

import wandb

if TYPE_CHECKING:
    from .conftest import InjectedGraphQLRequestCreator, RelayServerFixture


def test_commit_retries_on_500(
    relay_server: RelayServerFixture,
    wandb_init: Callable[[], wandb.wandb_sdk.wandb_run.Run],
    inject_graphql_response: "InjectedGraphQLRequestCreator",
):
    art = wandb.Artifact("test", "dataset")

    injected_resp = inject_graphql_response(
        operation_name="CommitArtifact",
        status=500,
        counter=1,
    )
    with relay_server(inject=[injected_resp]) as relay:
        run = wandb_init()
        logged = run.log_artifact(art).wait()
        run.finish()

    assert len(relay.context.entries[logged.id]["commit_artifact"]) == 2
