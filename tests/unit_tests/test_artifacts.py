import pytest

import wandb

from .conftest import InjectedGraphQLRequestCreator

def test_commit_retries_on_500(
    relay_server,
    wandb_init,
    inject_graphql_response: InjectedGraphQLRequestCreator,
):
    art = wandb.Artifact('test_TODO_1525', 'dataset')

    with relay_server(inject=[inject_graphql_response(operation_name="CommitArtifact", status=500, counter=1)]) as relay:
        run = wandb_init()
        run.log_artifact(art).wait()
        run.finish()
