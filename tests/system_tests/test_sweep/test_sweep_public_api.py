from __future__ import annotations

import pytest
import wandb
from wandb import Api
from wandb.apis.public.sweeps import Sweep
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb_gql import gql

from .test_wandb_sweep import (
    SWEEP_CONFIG_BAYES,
    SWEEP_CONFIG_GRID,
    SWEEP_CONFIG_GRID_NESTED,
    SWEEP_CONFIG_NO_NAME,
    SWEEP_CONFIG_RANDOM,
    VALID_SWEEP_CONFIGS_MINIMAL,
)

SWEEP_QUERY = gql(
    """
query Sweep($project: String, $entity: String, $name: String!) {
    project(name: $project, entityName: $entity) {
        sweep(sweepName: $name) {
            id
            name
            state
            runCountExpected
            bestLoss
            config
            priorRuns {
                edges {
                    node {
                        id
                        name
                    }
                }
            }
        }
    }
}
"""
)


@pytest.mark.parametrize(
    "sweep_config,expected_run_count",
    [
        (SWEEP_CONFIG_GRID, 3),
        (SWEEP_CONFIG_GRID_NESTED, 9),
        (SWEEP_CONFIG_BAYES, None),
        (SWEEP_CONFIG_RANDOM, None),
    ],
    ids=["test grid", "test grid nested", "test bayes", "test random"],
)
def test_sweep_api_expected_run_count(
    use_local_wandb_backend,
    user,
    sweep_config,
    expected_run_count,
):
    _ = use_local_wandb_backend
    _project = "test"
    with wandb.init(entity=user, project=_project) as run:
        run_id = run.id
        run.log({"x": 1})
        run.finish()
        sweep_id = wandb.sweep(
            sweep_config,
            entity=user,
            project=_project,
            prior_runs=[run_id],
        )

    api = Api()
    sweep = Sweep.get(api.client, user, _project, sweep_id, query=SWEEP_QUERY)

    assert sweep.expected_run_count == expected_run_count
    assert len(sweep._attrs["priorRuns"]["edges"]) == 1
    assert sweep._attrs["priorRuns"]["edges"][0]["node"]["name"] == run_id


def test_sweep_api_get_sweep_run(
    use_local_wandb_backend,
    user,
):
    sweep_config = SWEEP_CONFIG_GRID
    _ = use_local_wandb_backend
    project = "test"
    sweep_id = wandb.sweep(
        sweep_config,
        entity=user,
        project=project,
    )

    # Create a sweep run
    with wandb.init(
        entity=user, project=project, settings=wandb.Settings(sweep_id=sweep_id)
    ) as sweep_run:
        sweep_run.log({"y": 2})
        sweep_run_id = sweep_run.id

    api = Api()
    run = api.run(f"{user}/{project}/{sweep_run_id}")

    assert run.sweep.id == sweep_id
    assert run.summary_metrics.get("y") == 2


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_api(use_local_wandb_backend, user, sweep_config):
    _ = use_local_wandb_backend
    _project = "test"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    sweep = Api().sweep(f"{user}/{_project}/sweeps/{sweep_id}")

    assert sweep.entity == user
    assert f"{user}/{_project}/sweeps/{sweep_id}" in sweep.url
    assert sweep.state == "PENDING"
    assert str(sweep) == f"<Sweep {user}/test/{sweep_id} (PENDING)>"
    assert sweep.name == sweep_config["name"]
    assert sweep.path == [user, _project, sweep_id]


def test_sweep_no_name(use_local_wandb_backend, user):
    """Test that name for a sweep created with no config name is the sweep id."""
    _ = use_local_wandb_backend
    _project = "test"
    sweep_config = SWEEP_CONFIG_NO_NAME
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    sweep = Api().sweep(f"{user}/{_project}/sweeps/{sweep_id}")

    assert sweep.name == sweep_id


def test_sweep_with_edited_display_name(use_local_wandb_backend, user):
    """Test that name for a sweep with an updated displayName is the displayName."""
    _ = use_local_wandb_backend
    _project = "test"
    sweep_config = SWEEP_CONFIG_BAYES
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)
    original_sweep = Api().sweep(f"{user}/{_project}/sweeps/{sweep_id}")
    edited_display_name = "Updated Sweep Name"
    # Use internal API to update display name because there's no public API for it right now.
    # (It can currently only be edited in the UI.)
    InternalApi().upsert_sweep(
        config=sweep_config,
        obj_id=original_sweep._attrs[
            "id"
        ],  # Use the internal ID to update existing sweep
        entity=user,
        project=_project,
        display_name=edited_display_name,
    )

    updated_sweep = Api().sweep(f"{user}/{_project}/sweeps/{sweep_id}")

    assert original_sweep.name == sweep_config["name"]
    assert updated_sweep.name == edited_display_name


def test_from_path(user):
    api = Api()
    sweep_id = wandb.sweep(SWEEP_CONFIG_BAYES, entity=user, project="test")
    sweep = api.from_path(f"{user}/test/sweeps/{sweep_id}")
    assert isinstance(sweep, wandb.apis.public.Sweep)


def test_project_sweeps(user):
    run = wandb.init(entity=user, project="testnosweeps")
    run.finish()
    sweep_id = wandb.sweep(SWEEP_CONFIG_BAYES, entity=user, project="test")
    api = Api()
    project = api.from_path(f"{user}/test")
    psweeps = project.sweeps()
    assert len(psweeps) == 1
    assert psweeps[0].id == sweep_id

    no_sweeps_project = api.from_path("testnosweeps")
    nspsweeps = no_sweeps_project.sweeps()
    assert len(nspsweeps) == 0


def test_to_html(user):
    api = Api()
    sweep_id = wandb.sweep(SWEEP_CONFIG_BAYES, entity=user, project="test")
    sweep = api.from_path(f"{user}/test/sweeps/{sweep_id}")
    assert f"{user}/test/sweeps/{sweep_id}?jupyter=true" in sweep.to_html()
