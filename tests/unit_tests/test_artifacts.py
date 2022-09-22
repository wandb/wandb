from typing import TYPE_CHECKING

import wandb

if TYPE_CHECKING:
    from .conftest import InjectedGraphQLRequestCreator


def test_commit_retries_on_500(
    relay_server,
    wandb_init,
    inject_graphql_response: "InjectedGraphQLRequestCreator",
):
    art = wandb.Artifact("test", "dataset")

    injected_resp = inject_graphql_response(
        operation_name="CommitArtifact",
        status=500,
        counter=1,
    )
    with relay_server(inject=[injected_resp]):
        run = wandb_init()
        run.log_artifact(art).wait()
        run.finish()
