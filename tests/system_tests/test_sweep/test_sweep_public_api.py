import pytest
import wandb
from wandb import Api
from wandb.apis.public.sweeps import Sweep
from wandb_gql import gql

from .test_wandb_sweep import (
    SWEEP_CONFIG_BAYES,
    SWEEP_CONFIG_GRID,
    SWEEP_CONFIG_GRID_NESTED,
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


def test_from_path(user):
    api = Api()
    sweep_id = wandb.sweep(SWEEP_CONFIG_BAYES, entity=user, project="test")
    sweep = api.from_path(f"{user}/test/sweeps/{sweep_id}")
    assert isinstance(sweep, wandb.apis.public.Sweep)


def test_project_sweeps(user, wandb_init):
    run = wandb_init(entity=user, project="testnosweeps")
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
