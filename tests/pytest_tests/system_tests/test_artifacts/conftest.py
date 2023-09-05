import pytest
import wandb
from wandb.sdk.artifacts.artifact import Artifact


@pytest.fixture
def logged_artifact(wandb_init, user, example_files) -> Artifact:
    with wandb_init(entity=user, project="project") as run:
        artifact = wandb.Artifact("test-artifact", "dataset")
        artifact.add_dir(example_files)
        run.log_artifact(artifact)
    artifact.wait()
    return wandb.Api().artifact(f"{user}/project/test-artifact:v0")


@pytest.fixture
def linked_artifact(wandb_init, user, logged_artifact) -> Artifact:
    with wandb_init(entity=user, project="other-project") as run:
        run.link_artifact(logged_artifact, "linked-from-portfolio")

    return wandb.Api().artifact(f"{user}/other-project/linked-from-portfolio:v0")
