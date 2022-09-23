from typing import TYPE_CHECKING, Callable

import pytest
import wandb

if TYPE_CHECKING:
    from .conftest import InjectedGraphQLRequestCreator, RelayServerFixture


@pytest.mark.parametrize("status", [409, 500])
def test_commit_retries_on_right_statuses(
    relay_server: "RelayServerFixture",
    wandb_init: Callable[[], wandb.wandb_sdk.wandb_run.Run],
    inject_graphql_response: "InjectedGraphQLRequestCreator",
    status: int,
):
    art = wandb.Artifact("test", "dataset")

    injected_resp = inject_graphql_response(
        operation_name="CommitArtifact",
        status=status,
        counter=1,
    )
    with relay_server(inject=[injected_resp]) as relay:
        run = wandb_init()
        logged = run.log_artifact(art).wait()
        run.finish()

    # even though we made two requests, empirically only the successful one goes into the Context
    assert relay.context.entries[logged.id]["commit_artifact"]
