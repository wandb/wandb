"""Tests for the `wandb.apis.PublicApi` module."""

import json
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest
import requests
import wandb
import wandb.apis.public
import wandb.util
from wandb import Api
from wandb.old.summary import Summary


@pytest.mark.parametrize(
    "path",
    [
        "test/test/test/test",
        "test/test/test/test/test",
    ],
)
def test_from_path_bad_path(user, path):
    with pytest.raises(wandb.Error, match="Invalid path"):
        Api().from_path(path)


def test_from_path_bad_report_path(user):
    with pytest.raises(wandb.Error, match="Invalid report path"):
        Api().from_path("test/test/reports/test-foo")


@pytest.mark.parametrize(
    "path",
    [
        "test/test/reports/XYZ",
        "test/test/reports/Name-foo--XYZ",
    ],
)
def test_from_path_report_type(user, path):
    report = Api().from_path(path)
    assert isinstance(report, wandb.apis.public.BetaReport)


def test_project_to_html(user):
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        project = Api().from_path("test")
        assert "mock_entity/test/workspace?jupyter=true" in project.to_html()


@pytest.mark.xfail(
    reason="there is no guarantee that the backend has processed the event"
)
def test_run_metadata(user):
    project = "test_metadata"
    run = wandb.init(project=project)
    run.finish()

    metadata = Api().run(f"{run.entity}/{project}/{run.id}").metadata
    assert len(metadata)


@pytest.fixture
def stub_run_gql_once(user, wandb_backend_spy):
    """Helper fixture for stubbing out the 'Run' GraphQL query response.

    The fixture is a function that can be called to stub out the Run response.
    It returns a `wandb_backend_spy.gql.Responder` instance that can be used to
    assert on the interactions.
    """
    gql = wandb_backend_spy.gql

    def helper(
        id: str = user,
        config: Optional[Dict] = None,
        summary_metrics: Optional[Dict] = None,
    ):
        body = {
            "data": {
                "project": {
                    "internalId": "testinternalid",
                    "run": {
                        "id": id,
                        "tags": [],
                        "name": "test",
                        "displayName": "test",
                        "state": "finished",
                        "config": json.dumps(config or {}),
                        "group": "test",
                        "sweep_name": None,
                        "jobType": None,
                        "commit": None,
                        "readOnly": False,
                        "createdAt": "2023-11-05T17:46:35",
                        "heartbeatAt": "2023-11-05T17:46:36",
                        "description": "glamorous-frog-1",
                        "notes": None,
                        "systemMetrics": "{}",
                        "summaryMetrics": json.dumps(summary_metrics or {}),
                        "historyLineCount": 0,
                        "user": {
                            "name": "test",
                            "username": "test",
                        },
                    },
                },
            },
        }

        responder = gql.once(content=body)
        wandb_backend_spy.stub_gql(
            gql.Matcher(operation="Run"),
            responder,
        )
        return responder

    return helper


@pytest.fixture(scope="function")
def stub_run_full_history(wandb_backend_spy):
    """Helper fixture for stubbing out RunFullHistory."""

    gql = wandb_backend_spy.gql

    def helper(history: Optional[List] = None, events: Optional[List] = None):
        history = [json.dumps(h) for h in history or []]
        events = [json.dumps(e) for e in events or []]
        body = {
            "data": {
                "project": {
                    "run": {
                        "history": history,
                        "events": events,
                    },
                },
            },
        }

        responder = gql.Constant(content=body)
        wandb_backend_spy.stub_gql(
            gql.Matcher(operation="RunFullHistory"),
            responder,
        )
        return responder

    return helper


def test_from_path(stub_run_gql_once):
    spy = stub_run_gql_once()
    api = Api()

    run1 = api.from_path("test/test/test")
    run2 = api.from_path("test/test/test")

    # Second call should be cached and not make a second query.
    assert spy.total_calls == 1
    assert isinstance(run1, wandb.apis.public.Run)
    assert isinstance(run2, wandb.apis.public.Run)


def test_display(stub_run_gql_once):
    stub_run_gql_once()

    run = Api().from_path("test/test/test")

    assert not run.display()


def test_run_load(stub_run_gql_once):
    summary_metrics = {"acc": 100, "loss": 0}
    stub_run_gql_once(summary_metrics=summary_metrics)

    run = Api().run("test/test/test")

    assert run.summary_metrics == summary_metrics
    assert run.url.endswith("/test/test/runs/test")


def test_run_history(stub_run_gql_once, stub_run_full_history):
    history = [{"acc": 100, "loss": 0}]
    stub_run_gql_once()
    stub_run_full_history(history=history)

    run = Api().run("test/test/test")

    assert run.history(pandas=False)[0] == history[0]


def test_run_history_system(stub_run_gql_once, stub_run_full_history):
    events = [{"cpu": i * 10} for i in range(3)]
    stub_run_gql_once()
    stub_run_full_history(events=events)

    run = Api().run("test/test/test")

    assert run.history(stream="system", pandas=False) == events


def test_run_config(stub_run_gql_once):
    config = {"epochs": 10}
    stub_run_gql_once(config=config)

    run = Api().run("test/test/test")

    assert run.config == config


def test_run_history_keys(stub_run_gql_once, wandb_backend_spy):
    stub_run_gql_once()
    gql = wandb_backend_spy.gql
    history = [
        {"loss": 0, "acc": 100},
        {"loss": 1, "acc": 0},
    ]
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunSampledHistory"),
        gql.once(
            content={
                "data": {
                    "project": {
                        "run": {
                            "sampledHistory": [history],
                        },
                    },
                },
            }
        ),
    )

    run = Api().run("test/test/test")

    assert run.history(keys=["acc", "loss"], pandas=False) == history


def test_run_history_keys_bad_arg(stub_run_gql_once, mock_wandb_log):
    stub_run_gql_once()

    run = Api().run("test/test/test")

    run.history(keys="acc", pandas=False)
    mock_wandb_log.errored("keys must be specified in a list")

    run.history(keys=[["acc"]], pandas=False)
    mock_wandb_log.errored("keys argument must be a list of strings")

    run.scan_history(keys="acc")
    mock_wandb_log.errored("keys must be specified in a list")

    run.scan_history(keys=[["acc"]])
    mock_wandb_log.errored("keys argument must be a list of strings")


def test_run_summary(wandb_backend_spy):
    seed_run = Api().create_run()
    run = Api().run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
    run.summary.update({"cool": 1000})

    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.summary(run_id=run.storage_id)["cool"] == 1000


def test_run_create(user, wandb_backend_spy):
    gql = wandb_backend_spy.gql
    upsert_bucket_spy = gql.Capture()
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="UpsertBucket"),
        upsert_bucket_spy,
    )

    Api().create_run(project="test")

    assert upsert_bucket_spy.total_calls == 1
    assert upsert_bucket_spy.requests[0].variables["entity"] == user
    assert upsert_bucket_spy.requests[0].variables["project"] == "test"


def test_run_update(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    upsert_bucket_spy = gql.Capture()
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="UpsertBucket"),
        upsert_bucket_spy,
    )

    seed_run = wandb.init(config={"foo": "not_bar"})
    seed_run.log(dict(acc=100, loss=0))
    seed_run.finish()

    run = Api().run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
    wandb_key = run.rawconfig["_wandb"]
    run.tags.append("test")
    run.config["foo"] = "bar"
    run.update()

    # run.update() triggers two UpdateBucket calls;
    # the second one just updates the summary.
    update_request = upsert_bucket_spy.requests[-2]
    assert update_request.variables["entity"] == seed_run.entity
    assert update_request.variables["tags"] == ["test"]
    config = json.loads(update_request.variables["config"])
    assert config["foo"]["value"] == "bar"
    assert config["_wandb"]["value"] == wandb_key


def test_run_delete(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    delete_spy = gql.Capture()
    wandb_backend_spy.stub_gql(gql.Matcher(operation="DeleteRun"), delete_spy)

    seed_run = Api().create_run()
    run = Api().run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")

    run.delete()
    run.delete(delete_artifacts=True)

    assert delete_spy.total_calls == 2
    assert not delete_spy.requests[0].variables["deleteArtifacts"]
    assert delete_spy.requests[1].variables["deleteArtifacts"]


def test_run_file_direct(
    user,
    stub_run_gql_once,
    wandb_backend_spy,
):
    file_name = "weights.h5"
    direct_url = f"https://api.wandb.ai/storage?file={file_name}&direct=true"
    stub_run_gql_once()
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunFiles"),
        gql.once(
            content={
                "data": {
                    "project": {
                        "run": {
                            "files": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "RmlsZToxODMw",
                                            "name": file_name,
                                            "directUrl": direct_url,
                                        }
                                    },
                                ],
                            },
                        },
                    },
                },
            }
        ),
    )

    run = Api().run(f"{user}/test/test")

    file = run.file(file_name)
    assert file.direct_url == direct_url


# TODO: how to seed this run faster?
def test_run_retry(wandb_backend_spy):
    with wandb.init() as seed_run:
        seed_run.log(dict(acc=100, loss=0))

    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.any(),
        gql.once(content={"errors": ["Server down"]}, status=500),
    )

    run = Api().run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")

    assert run.summary_metrics["acc"] == 100
    assert run.summary_metrics["loss"] == 0


def test_runs_from_path_index(wandb_backend_spy):
    num_runs = 4
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="Runs"),
        gql.once(
            content={
                "data": {
                    "project": {
                        "runCount": num_runs,
                        "runs": {
                            "edges": [
                                {
                                    "node": {"name": f"test_{i}", "sweepName": None},
                                }
                                for i in range(num_runs)
                            ],
                        },
                    },
                },
            },
        ),
    )

    runs = Api().runs("test/test")

    assert len(runs) == num_runs
    assert runs[3]
    assert len(runs.objects) == num_runs


def test_runs_from_path(user, wandb_backend_spy):
    num_runs, per_page = 4, 2
    ratio = num_runs // per_page
    summary_metrics = {"acc": 100, "loss": 0}
    group = "A"
    job_type = "test"
    body = {
        "data": {
            "project": {
                "runCount": num_runs,
                "runs": {
                    "edges": [
                        {
                            "node": {
                                "name": f"test_{i}",
                                "sweepName": None,
                                "group": group,
                                "jobType": job_type,
                                "summaryMetrics": json.dumps(summary_metrics),
                            },
                        }
                        for i in range(ratio)
                    ],
                    "pageInfo": {
                        "hasNextPage": True,
                    },
                },
            },
        },
    }
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="Runs"),
        gql.Constant(content=body),
    )

    runs = Api().runs(f"{user}/test", per_page=per_page)

    assert len(runs) == 4
    assert len(runs.objects) == 2
    assert runs[0].summary_metrics == summary_metrics
    assert runs[0].group == group
    assert runs[0].job_type == job_type


def test_projects(user, wandb_backend_spy):
    num_projects = 2
    body = {
        "data": {
            "models": {
                "edges": [
                    {
                        "node": {"name": f"test_{i}", "entityName": user},
                    }
                    for i in range(num_projects)
                ],
                "pageInfo": {
                    "hasNextPage": False,
                },
            },
        },
    }
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="Projects"),
        gql.Constant(content=body),
    )

    projects = Api().projects(user)

    # projects doesn't provide a length for now, so we iterate
    # them all to count
    assert sum([1 for _ in projects]) == 2


def test_delete_file(
    user,
    stub_run_gql_once,
    wandb_backend_spy,
):
    stub_run_gql_once()
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunFiles"),
        gql.once(
            content={
                "data": {
                    "project": {
                        "run": {
                            "files": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "RmlsZToxODMw",
                                            "name": "test.txt",
                                        }
                                    },
                                ],
                            },
                        },
                    },
                }
            }
        ),
    )
    delete_spy = gql.once(content={"data": {"deleteFiles": {"success": True}}})
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="deleteFiles"),
        delete_spy,
    )

    run = Api().run(f"{user}/test/test")
    file = run.files()[0]
    file.delete()

    # For system tests on newer server version, the projectId is provided
    if file._server_accepts_project_id_for_delete_file():
        assert "projectId" in delete_spy.requests[0].variables
        assert "projectId" in delete_spy.requests[0].query
        assert delete_spy.requests[0].variables == {
            "files": [file.id],
            "projectId": run._project_internal_id,
        }
    # For some older server versions, the projectId is not provided
    else:
        assert "projectId" not in delete_spy.requests[0].variables
        assert "projectId" not in delete_spy.requests[0].query
        assert delete_spy.requests[0].variables == {
            "files": [file.id],
        }


def test_nested_summary(user, stub_run_gql_once):
    stub_run_gql_once()

    run = Api().run(f"{user}/test/test")

    summary_dict = {"a": {"b": {"c": 0.9}}}
    summary = Summary(run, summary_dict)
    assert summary["a"]["b"]["c"] == 0.9


def test_to_html(user, stub_run_gql_once):
    stub_run_gql_once()

    run = Api().run("test/test")

    assert f"{user}/test/runs/test?jupyter=true" in run.to_html()


def test_query_team(user, api):
    t = api.team(user)
    assert t.name == user
    assert t.members[0].account_type == "USER"
    assert repr(t.members[0]) == f"<Member {user} (USER)>"


def test_viewer(user, api):
    v = api.viewer
    assert v.admin is False
    assert v.username == user
    assert v.api_keys == [user]
    assert v.teams == [user]


def test_create_team_exists(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.any(),
        gql.Constant(content={"error": "resource already exists"}, status=409),
    )

    with pytest.raises(requests.exceptions.HTTPError):
        Api().create_team("test")


def fake_search_users_response(
    email: str,
    api_keys: Dict[str, str],
    teams: List[str],
    count: int = 1,
) -> Dict[str, Any]:
    """Returns a fake response to a SearchUsers GraphQL query."""
    return {
        "data": {
            "users": {
                "edges": [
                    {
                        "node": {
                            "email": email,
                            "apiKeys": {"edges": [{"node": key} for key in api_keys]},
                            "teams": {
                                "edges": [{"node": team} for team in teams],
                            },
                        },
                    }
                ]
                * count,
            },
        },
    }


@pytest.fixture
def stub_search_users(wandb_backend_spy):
    """Fixture to stub a SearchUsers GraphQL query."""
    gql = wandb_backend_spy.gql

    def helper(
        email: str,
        api_keys: Dict[str, str],
        teams: List[str],
        count: int = 1,
    ):
        search_users_spy = gql.Constant(
            content=fake_search_users_response(
                email,
                api_keys,
                teams,
                count,
            )
        )

        wandb_backend_spy.stub_gql(
            gql.Matcher(operation="SearchUsers"),
            search_users_spy,
        )

        return search_users_spy

    return helper


def test_query_user(stub_search_users):
    email = "test@test.com"
    api_keys = [{"name": "Y" * 40}]
    teams = [{"name": "test"}]
    stub_search_users(email=email, api_keys=api_keys, teams=teams)

    u = Api().user("test")

    assert u.email == email
    assert u.api_keys == [api_keys[0]["name"]]
    assert u.teams == [teams[0]["name"]]
    assert repr(u) == f"<User {email}>"


def test_query_user_multiple(stub_search_users):
    email = "test@test.com"
    stub_search_users(email=email, api_keys=[], teams=[], count=2)

    api = Api()

    assert api.user(email).email == email
    assert len(api.users(email)) == 2


def test_create_team(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="CreateTeam"),
        gql.Constant(
            content={
                "data": {
                    "createTeam": {
                        "team": {
                            "name": "test",
                        },
                    },
                },
            }
        ),
    )

    t = Api().create_team("test")

    assert t.name == "test"
    assert repr(t) == "<Team test>"


def test_delete_api_key_success(wandb_backend_spy, stub_search_users):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="DeleteApiKey"),
        gql.once(content={"data": {"deleteApiKey": {"success": True}}}),
    )
    email = "test@test.com"
    api_key = {"name": "X" * 40, "id": "QXBpS2V5OjE4MzA="}
    stub_search_users(email=email, api_keys=[api_key], teams=[])

    user = Api().user(email)

    assert user.delete_api_key(api_key["name"])


def test_delete_api_key_failure(wandb_backend_spy, stub_search_users):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="DeleteApiKey"),
        gql.once(
            content={"data": {"deleteApiKey": {"success": False}}},
            status=409,
        ),
    )
    email = "test@test.com"
    api_key = {"name": "X" * 40, "id": "QXBpS2V5OjE4MzA="}
    stub_search_users(email=email, api_keys=[api_key], teams=[])

    user = Api().user(email)

    assert not user.delete_api_key(api_key["name"])


def test_generate_api_key_success(wandb_backend_spy, stub_search_users):
    email = "test@test.com"
    api_key_1 = {"name": "X" * 40, "id": "QXBpS2V5OjE4MzA="}
    api_key_2 = {"name": "Y" * 40, "id": "QXBpS2V5OjE4MzE="}
    stub_search_users(email=email, api_keys=[api_key_1], teams=[])
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="GenerateApiKey"),
        gql.once(content={"data": {"generateApiKey": {"apiKey": api_key_2}}}),
    )

    user = Api().user(email)
    old_key = user.api_keys[0]
    new_key = user.generate_api_key("good")

    assert old_key == api_key_1["name"]
    assert new_key == api_key_2["name"]
    assert user.api_keys[-1] == new_key


def test_generate_api_key_failure(wandb_backend_spy, stub_search_users):
    email = "test@test.com"
    api_key = {"name": "X" * 40, "id": "QXBpS2V5OjE4MzA="}
    stub_search_users(email=email, api_keys=[api_key], teams=[])
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="GenerateApiKey"),
        gql.once(content={"error": "resource already exists"}, status=409),
    )

    user = Api().user(email)

    assert user.generate_api_key("conflict") is None


def test_runs_histories(
    stub_run_gql_once,
    stub_run_full_history,
    wandb_backend_spy,
):
    # Inject the dummy run data
    stub_run_gql_once(id="test_1")

    # Inject the dummy project and run data required by the Runs class
    body = {
        "data": {
            "project": {
                "runCount": 1,
                "runs": {
                    "edges": [
                        {
                            "node": {
                                "name": "test_1",
                                "historyKeys": None,
                                "sweepName": None,
                                "state": "finished",
                                "config": "{}",
                                "systemMetrics": "{}",
                                "summaryMetrics": "{}",
                                "tags": [],
                                "description": None,
                                "notes": None,
                                "createdAt": "2023-11-05T17:46:35",
                                "heartbeatAt": "2023-11-05T17:46:36",
                                "user": {
                                    "name": "test",
                                    "username": "test",
                                },
                            }
                        },
                    ],
                    "pageInfo": {"endCursor": None, "hasNextPage": False},
                },
            },
        },
    }
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="Runs"),
        gql.once(content=body),
    )

    # Inject dummy history data for the run
    history_run_1 = [
        {
            "_step": 1,
            "metric1": 0.1,
            "metric2": 0.2,
            "metric3": 0.3,  # test for different shape
            "system_metric1": 10,
            "run_id": "test_1",
        },
        {
            "_step": 2,
            "metric1": 0.4,
            "metric2": 0.5,
            "system_metric1": 20,
            "run_id": "test_1",
        },
    ]
    stub_run_full_history(history=history_run_1)

    api = Api()
    runs = api.runs("test/test")

    all_histories = runs.histories(samples=2, format="default")
    assert len(all_histories) == 2
    assert all_histories[0]["_step"] == 1
    assert all_histories[0]["metric1"] == 0.1
    assert all_histories[0]["metric2"] == 0.2
    assert all_histories[0]["metric3"] == 0.3
    assert all_histories[0]["system_metric1"] == 10
    assert all_histories[1]["_step"] == 2
    assert all_histories[1]["metric1"] == 0.4
    assert all_histories[1]["metric2"] == 0.5
    assert all_histories[1]["system_metric1"] == 20

    all_histories_pandas = runs.histories(samples=2, format="pandas")
    assert all_histories_pandas.shape == (2, 6)
    assert "_step" in all_histories_pandas.columns
    assert "metric1" in all_histories_pandas.columns
    assert "metric2" in all_histories_pandas.columns
    assert "metric3" in all_histories_pandas.columns
    assert "system_metric1" in all_histories_pandas.columns

    all_histories_polars = runs.histories(samples=2, format="polars")
    assert all_histories_polars.shape == (2, 6)
    assert "_step" in all_histories_polars.columns
    assert "metric1" in all_histories_polars.columns
    assert "metric2" in all_histories_polars.columns
    assert "metric3" in all_histories_polars.columns
    assert "system_metric1" in all_histories_polars.columns


def test_runs_histories_empty(wandb_backend_spy):
    # Inject the dummy project and run data required by the Runs class
    body = {
        "data": {
            "project": {
                "runCount": 1,
                "runs": {
                    "edges": [],
                    "pageInfo": {"endCursor": None, "hasNextPage": False},
                },
            },
        },
    }

    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="Runs"),
        gql.once(content=body),
    )

    api = Api()
    runs = api.runs("test/test")

    assert not runs.histories(format="default")  # empty list
    for format in ("pandas", "polars"):
        assert runs.histories(samples=2, format=format).shape == (0, 0)
