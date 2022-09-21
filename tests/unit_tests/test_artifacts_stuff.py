import random
import tempfile
import wandb
from .conftest import InjectedGraphQLRequestCreator


def test_stuff(
    relay_server,
    wandb_init,
    inject_graphql_response: InjectedGraphQLRequestCreator,
):
    art = wandb.Artifact('test_TODO_1525', 'dataset')
    with tempfile.NamedTemporaryFile(mode='wb') as f:
        f.write(bytes(random.randrange(256) for _ in range(100)))
        art.add_file(f.name)

    with relay_server(inject=[inject_graphql_response(operation_name="CommitArtifact", status=409, counter=1)]) as relay:
        # breakpoint()
        run = wandb_init()
        logged = run.log_artifact(art).wait()
        run.finish()

    assert relay.context.entries[logged.id]['commit_artifact']
