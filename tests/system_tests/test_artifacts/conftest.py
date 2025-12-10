from __future__ import annotations

import wandb
from pytest import fixture
from wandb import Api
from wandb.sdk.artifacts.artifact import Artifact


@fixture
def logged_artifact(user: str, example_files, api: Api) -> Artifact:
    with wandb.init(entity=user, project="project") as run:
        artifact = wandb.Artifact("test-artifact", "dataset")
        artifact.add_dir(example_files)
        run.log_artifact(artifact)
    artifact.wait()
    return api.artifact(f"{user}/project/test-artifact:v0")


@fixture
def linked_artifact(user: str, logged_artifact: Artifact, api: Api) -> Artifact:
    with wandb.init(entity=user, project="other-project") as run:
        run.link_artifact(logged_artifact, "linked-from-portfolio")

    return api.artifact(f"{user}/other-project/linked-from-portfolio:v0")
