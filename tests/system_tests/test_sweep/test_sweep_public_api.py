import json

import pytest
import wandb
from wandb import Api
from wandb.apis.public.sweeps import Sweep
from wandb.errors import UnsupportedError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal.internal_api import Api as InternalApi

from tests.fixtures.wandb_backend_spy import WandbBackendSpy

from .test_wandb_sweep import (
    SWEEP_CONFIG_BAYES,
    SWEEP_CONFIG_GRID,
    SWEEP_CONFIG_GRID_NESTED,
    SWEEP_CONFIG_NO_NAME,
    SWEEP_CONFIG_RANDOM,
    VALID_SWEEP_CONFIGS_MINIMAL,
)

SWEEP_QUERY = """
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
    sweep = Sweep.get(
        api,
        user,
        _project,
        sweep_id,
        query=SWEEP_QUERY,
    )

    assert sweep is not None
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


def _stub_sweeps_query_filtering(spy: WandbBackendSpy, *, enabled: bool) -> None:
    """Stub the server's reported support for the SWEEPS_QUERY_FILTERING feature."""
    features = (
        [{"name": pb.ServerFeature.Name(pb.SWEEPS_QUERY_FILTERING), "isEnabled": True}]
        if enabled
        else []
    )
    gql = spy.gql
    spy.stub_gql(
        gql.Matcher(operation="ServerFeaturesQuery"),
        gql.Constant(content={"data": {"serverInfo": {"features": features}}}),
    )


def test_project_sweeps_filtering_unsupported(wandb_backend_spy, user):
    """Filtering fails fast when the server doesn't support SWEEPS_QUERY_FILTERING."""
    sweep_id = wandb.sweep(SWEEP_CONFIG_BAYES, entity=user, project="test")
    _stub_sweeps_query_filtering(wandb_backend_spy, enabled=False)

    project = Api().from_path(f"{user}/test")

    # Listing sweeps without filters still works (the `filters` arg is omitted).
    assert len(project.sweeps()) == 1

    # Requesting filters fails fast rather than silently returning everything.
    with pytest.raises(
        UnsupportedError,
        match="Filtering sweeps is not supported on this W&B server version",
    ):
        project.sweeps(filters={"name": sweep_id})


def test_project_sweeps_filtering_supported(wandb_backend_spy, user):
    """When supported, the `filters` arg is forwarded to the server."""
    wandb.sweep(SWEEP_CONFIG_BAYES, entity=user, project="test")
    _stub_sweeps_query_filtering(wandb_backend_spy, enabled=True)

    gql = wandb_backend_spy.gql
    get_sweeps = gql.Constant(
        content={
            "data": {
                "project": {
                    "totalSweeps": 1,
                    "sweeps": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [],
                    },
                }
            }
        }
    )
    wandb_backend_spy.stub_gql(gql.Matcher(operation="GetSweeps"), get_sweeps)

    project = Api().from_path(f"{user}/test")
    filters = {"name": "my-sweep"}
    assert len(project.sweeps(filters=filters)) == 1

    # The filter was forwarded to the server as the `filters` argument.
    assert get_sweeps.total_calls >= 1
    request = get_sweeps.requests[0]
    assert "filters" in request.query
    assert json.loads(request.variables["filters"]) == filters
