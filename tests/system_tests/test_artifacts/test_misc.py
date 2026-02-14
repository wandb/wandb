from __future__ import annotations

import re
import time
import uuid
from operator import attrgetter
from pathlib import Path

import numpy as np
import wandb
from pytest import fail, raises
from wandb import Api
from wandb.apis import public


def assert_eq_runs(
    run_a: wandb.Run | public.Run, run_b: wandb.Run | public.Run
) -> None:
    __tracebackhide__ = True

    # See: https://docs.pytest.org/en/stable/example/simple.html#writing-well-integrated-assertion-helpers
    if run_a.id != run_b.id:
        fail(f"Run.id does not match: {run_a.id!r} != {run_b.id!r}")

    if run_a.entity != run_b.entity:
        fail(f"Run.entity does not match: {run_a.entity!r} != {run_b.entity!r}")

    if run_a.project != run_b.project:
        fail(f"Run.project does not match: {run_a.project!r} != {run_b.project!r}")


def test_artifact_run_lookup_apis(user):
    artifact_1_name = f"a1-{time.time()}"
    artifact_2_name = f"a2-{time.time()}"

    artifact_type = "test_type"

    # Initial setup
    with wandb.init() as run_a:
        artifact_a1 = wandb.Artifact(artifact_1_name, artifact_type)
        artifact_a1.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
        run_a.log_artifact(artifact_a1)

        artifact_a2 = wandb.Artifact(artifact_2_name, artifact_type)
        artifact_a2.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
        run_a.log_artifact(artifact_a2)

    # Create a second version for a1
    with wandb.init() as run_b:
        artifact_b1 = wandb.Artifact(artifact_1_name, artifact_type)
        artifact_b1.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
        run_b.log_artifact(artifact_b1)

    # Use both
    with wandb.init() as run_c:
        a1 = run_c.use_artifact(f"{artifact_1_name}:latest")

        a1_used_by = a1.used_by()
        assert len(a1_used_by) == 1
        assert_eq_runs(a1_used_by[0], run_c)

        a1_logged_by = a1.logged_by()
        assert a1_logged_by is not None
        assert_eq_runs(a1_logged_by, run_b)

        a2 = run_c.use_artifact(f"{artifact_2_name}:latest")
        a2_used_by = a2.used_by()
        assert len(a2_used_by) == 1
        assert_eq_runs(a2_used_by[0], run_c)

        a2_logged_by = a2.logged_by()
        assert a2_logged_by is not None
        assert_eq_runs(a2_logged_by, run_a)

    # Use both
    with wandb.init() as run_d:
        # Order by ID for deterministic comparison
        expected_used_by = sorted([run_c, run_d], key=attrgetter("id"))

        a1 = run_d.use_artifact(f"{artifact_1_name}:latest")
        a1_used_by = sorted(a1.used_by(), key=attrgetter("id"))
        assert len(a1_used_by) == 2
        for expected_run, actual_run in zip(expected_used_by, a1_used_by):
            assert_eq_runs(expected_run, actual_run)

        a2 = run_d.use_artifact(f"{artifact_2_name}:latest")
        a2_used_by = sorted(a2.used_by(), key=attrgetter("id"))
        assert len(a2_used_by) == 2
        for expected_run, actual_run in zip(expected_used_by, a2_used_by):
            assert_eq_runs(expected_run, actual_run)


def test_duplicate_artifact_skips_upload(user, tmp_path: Path, api: Api):
    artifact_name = f"dedup-{uuid.uuid4().hex[:16]}"
    artifact_type = "dataset"

    # Fixed content so digest is same.
    data_file = tmp_path / "data.txt"
    data_file.write_text("I shall not change")

    # First run create v0
    with wandb.init() as run_a:
        art = wandb.Artifact(artifact_name, artifact_type)
        art.add_file(str(data_file))
        run_a.log_artifact(art)

    # Second run log is a essentially a noop, no new version is created.
    with wandb.init() as run_b:
        art = wandb.Artifact(artifact_name, artifact_type)
        art.add_file(str(data_file))
        run_b.log_artifact(art)

    # Verify only one version was created.
    versions = list(api.artifacts(artifact_type, artifact_name))
    assert len(versions) == 1, (
        f"Expected 1 artifact version (digest dedup), got {len(versions)}: "
        + ", ".join(v.name for v in versions)
    )


def test_artifact_creation_with_diff_type(user):
    artifact_name = f"a1-{time.time()}"

    # create
    with wandb.init() as run_a:
        artifact_a = wandb.Artifact(artifact_name, "artifact_type_1")
        artifact_a.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
        run_a.log_artifact(artifact_a)

    # update
    with wandb.init() as run_b:
        artifact_b = wandb.Artifact(artifact_name, "artifact_type_1")
        artifact_b.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image")
        run_b.log_artifact(artifact_b)

    # invalid
    with wandb.init() as run_c:
        artifact_c = wandb.Artifact(artifact_name, "artifact_type_2")
        artifact_c.add(wandb.Image(np.random.randint(0, 255, (10, 10))), "image_2")
        expected_msg = (
            f"Artifact {artifact_name} already exists with type 'artifact_type_1'; "
            "cannot create another with type 'artifact_type_2'"
        )
        with raises(ValueError, match=re.escape(expected_msg)):
            run_c.log_artifact(artifact_c)

    with wandb.init() as run_d:
        used_artifact = run_d.use_artifact(f"{artifact_name}:latest")

        # should work
        assert used_artifact.get("image") is not None

        # should not work
        assert used_artifact.get("image_2") is None
