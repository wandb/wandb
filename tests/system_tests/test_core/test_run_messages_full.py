"""Integration tests for the run_messages mechanism."""

import pytest
import wandb

from tests.fixtures.mock_wandb_log import MockWandbLog


@pytest.mark.parametrize("mode", ["online", "offline"])
@pytest.mark.usefixtures("user")  # online mode requires an authenticated user
def test_prints_run_messages(mock_wandb_log: MockWandbLog, mode: str):
    with wandb.init(mode=mode) as run:
        run.log({"x": 3}, step=3)
        run.log({"x": 2}, step=2)

    mock_wandb_log.assert_warned(
        "Tried to log to step 2 that is less than the current step 3",
    )


def test_prints_artifact_save_failure(
    mock_wandb_log: MockWandbLog,
    wandb_backend_spy,
):
    gql = wandb_backend_spy.gql
    # A persistent GraphQL error is not retried, unlike a 5xx response.
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="CreateArtifact"),
        gql.Constant(content={"errors": [{"message": "forced artifact failure"}]}),
    )

    with wandb.init() as run:
        artifact = wandb.Artifact("failing-artifact", "dataset")
        run.log_artifact(artifact)  # no wait()

    mock_wandb_log.assert_warned(
        'Failed to save artifact "failing-artifact" (type "dataset")',
    )
    mock_wandb_log.assert_warned("forced artifact failure")
