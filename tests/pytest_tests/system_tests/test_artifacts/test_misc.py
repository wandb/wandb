import os
import shutil
import time

import numpy as np
import pytest
import wandb


@pytest.fixture
def cleanup():
    yield
    _cleanup()


def _cleanup():
    wandb.finish()
    if os.path.isdir("wandb"):
        shutil.rmtree("wandb")
    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")


def _run_eq(run_a, run_b):
    return (
        run_a.id == run_b.id
        and run_a.entity == run_b.entity
        and run_a.project == run_b.project
    )


def _runs_eq(runs_a, runs_b, sort=True):
    if sort:
        runs_a = sorted(runs_a, key=lambda run: run.id)
        runs_b = sorted(runs_b, key=lambda run: run.id)
    return all([_run_eq(run_a, run_b) for run_a, run_b in zip(runs_a, runs_b)])


def test_artifact_run_lookup_apis(user, cleanup):
    artifact_1_name = f"a1-{str(time.time())}"
    artifact_2_name = f"a2-{str(time.time())}"

    # Initial setup
    run_1 = wandb.init()
    artifact = wandb.Artifact(artifact_1_name, "test_type")
    artifact.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
    run_1.log_artifact(artifact)
    artifact = wandb.Artifact(artifact_2_name, "test_type")
    artifact.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
    run_1.log_artifact(artifact)
    run_1.finish()

    # Create a second version for a1
    run_2 = wandb.init()
    artifact = wandb.Artifact(artifact_1_name, "test_type")
    artifact.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
    run_2.log_artifact(artifact)
    run_2.finish()

    # Use both
    run_3 = wandb.init()
    a1 = run_3.use_artifact(artifact_1_name + ":latest")
    assert _runs_eq(a1.used_by(), [run_3])
    assert _run_eq(a1.logged_by(), run_2)
    a2 = run_3.use_artifact(artifact_2_name + ":latest")
    assert _runs_eq(a2.used_by(), [run_3])
    assert _run_eq(a2.logged_by(), run_1)
    run_3.finish()

    # Use both
    run_4 = wandb.init()
    a1 = run_4.use_artifact(artifact_1_name + ":latest")
    assert _runs_eq(a1.used_by(), [run_3, run_4])
    a2 = run_4.use_artifact(artifact_2_name + ":latest")
    assert _runs_eq(a2.used_by(), [run_3, run_4])
    run_4.finish()


def test_artifact_creation_with_diff_type(user, cleanup):
    artifact_name = f"a1-{str(time.time())}"

    # create
    with wandb.init() as run:
        artifact = wandb.Artifact(artifact_name, "artifact_type_1")
        artifact.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
        run.log_artifact(artifact)

    # update
    with wandb.init() as run:
        artifact = wandb.Artifact(artifact_name, "artifact_type_1")
        artifact.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
        run.log_artifact(artifact)

    # invalid
    with wandb.init() as run:
        artifact = wandb.Artifact(artifact_name, "artifact_type_2")
        artifact.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image_2")
        did_err = False
        try:
            run.log_artifact(artifact)
        except ValueError as err:
            did_err = True
            assert (
                str(err)
                == f"Artifact {artifact_name} already exists with type 'artifact_type_1';"
                " cannot create another with type 'artifact_type_2'"
            )
        assert did_err

    with wandb.init() as run:
        artifact = run.use_artifact(artifact_name + ":latest")
        # should work
        image = artifact.get("image")
        assert image is not None
        # should not work
        image_2 = artifact.get("image_2")
        assert image_2 is None
