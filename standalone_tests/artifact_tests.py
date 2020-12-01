import wandb
import numpy as np
import time
import shutil

def teardown():
    wandb.finish()
    shutil.rmtree("wandb")

def _run_eq(run_a, run_b):
    return (
        run_a.id == run_b.id and
        run_a.entity == run_b.entity and
        run_a.project == run_b.project
    )

def _runs_eq(runs_a, runs_b):
    return all([_run_eq(run_a, run_b) for run_a, run_b in zip(runs_a, runs_b)])

def test_artifact_run_lookup_apis():
    artifact_1_name = "a1-{}".format(str(time.time()))
    artifact_2_name = "a2-{}".format(str(time.time()))

    # Initial setup
    run_1 = wandb.init()
    artifact = wandb.Artifact(artifact_1_name, "test_type");
    artifact.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
    run_1.log_artifact(artifact)
    artifact = wandb.Artifact(artifact_2_name, "test_type");
    artifact.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
    run_1.log_artifact(artifact)
    run_1.finish()

    # Create a second version for a1
    run_2 = wandb.init()
    artifact = wandb.Artifact(artifact_1_name, "test_type");
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


if __name__ == "__main__":
    try:
        test_artifact_run_lookup_apis()
    finally:
        teardown()
