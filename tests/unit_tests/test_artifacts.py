import pytest

import wandb

from .conftest import InjectedGraphQLRequestCreator

@pytest.mark.parametrize('status', [409, 500])
def test_commit_retries_on_right_statuses(
    relay_server,
    wandb_init,
    inject_graphql_response: InjectedGraphQLRequestCreator,
    status: int,
):
    art = wandb.Artifact('test', 'dataset')

    with relay_server(inject=[inject_graphql_response(operation_name="CommitArtifact", status=status, counter=1)]) as relay:
        run = wandb_init()
        run.log_artifact(art).wait()
        run.finish()
