"""This tests the guardrail for when history step was introduced into the SDK (0.12.12).
Basically, it grabs the max_cli_version that the backend (either cloud or local) knows about and
makes sure that we only include the history step info into the gql query if this max_cli_version >= 0.12.12.
"""

import wandb


def func():
    entity, project = None, None
    run_id = None
    with wandb.init() as run:
        run_id = run.id
        artifact = wandb.Artifact(f"boom-name-{run_id}", type="boom-type")
        table = wandb.Table(columns=["boom_col"])
        table.add_data(5)
        artifact.add(table, name="table")
        wandb.log({"data": 5})
        wandb.log({"data": 10})
        wandb.log_artifact(artifact)

        entity = run.entity
        project = run.project

    api = wandb.Api()
    api.artifact(f"{entity}/{project}/boom-name-{run_id}:v0")
    assert True


if __name__ == "__main__":
    func()
