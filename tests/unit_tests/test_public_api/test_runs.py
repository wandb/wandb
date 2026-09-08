import json
from copy import deepcopy
from typing import Any
from unittest import mock

import pytest
import wandb
from wandb.apis.public.runs import Run, RunNotFoundError, Runs
from wandb.apis.public.sweeps import Sweep
from wandb.proto import wandb_api_pb2 as apb


@pytest.mark.parametrize("lazy", [True, False])
def test_runs_reject_nested_tag_list(lazy: bool) -> None:
    service_api = mock.MagicMock()
    filters = {"tags": {"$all": [["sgd"], "test"], "$nin": ["test-2"]}}
    original_filters = deepcopy(filters)

    with pytest.raises(
        ValueError,
        match=r"filters\.tags\.\$all\[0\]: expected a tag string",
    ):
        Runs(service_api, "entity", "project", filters=filters, lazy=lazy)

    service_api.execute_graphql.assert_not_called()
    assert filters == original_filters


@pytest.mark.parametrize(
    "filters,error_path",
    [
        ({"tags": {"$all": "sgd"}}, "filters.tags.$all"),
        ({"tags": {"$in": None}}, "filters.tags.$in"),
        ({"tags": {"$nin": {"tag": "sgd"}}}, "filters.tags.$nin"),
        ({"tags": {"$all": 1}}, "filters.tags.$all"),
        ({"tags": {"$all": [{"tag": "sgd"}]}}, "filters.tags.$all[0]"),
        ({"tags": {"$in": [1]}}, "filters.tags.$in[0]"),
        ({"tags": {"$nin": [None]}}, "filters.tags.$nin[0]"),
        ({"tags": {"$in": [("sgd",)]}}, "filters.tags.$in[0]"),
        ({"tags": {"$nin": [["sgd"]]}}, "filters.tags.$nin[0]"),
        ({"tags": [["sgd"]]}, "filters.tags[0]"),
        ({"tags": (("sgd",),)}, "filters.tags[0]"),
        ({"tags": ["sgd", 1]}, "filters.tags[1]"),
        ({"tags": [None]}, "filters.tags[0]"),
        ({"tags": [{"tag": "sgd"}]}, "filters.tags[0]"),
        ({"$and": {"state": "finished"}}, "filters.$and"),
        ({"$or": "sgd"}, "filters.$or"),
        ({"$nor": None}, "filters.$nor"),
        ({"$and": [None]}, "filters.$and[0]"),
        ({"$or": ["sgd"]}, "filters.$or[0]"),
        ({"$nor": [[]]}, "filters.$nor[0]"),
        (
            {"$and": [{"$or": ({"$nor": [{"tags": {"$all": [["sgd"]]}}]},)}]},
            "filters.$and[0].$or[0].$nor[0].tags.$all[0]",
        ),
        ({"$all": ["sgd"]}, "filters.$all"),
        ({"$in": ["group-1"]}, "filters.$in"),
        ({"$nin": ["group-1"]}, "filters.$nin"),
        ({"$or": [{"$in": ["group-1"]}]}, "filters.$or[0].$in"),
        ([], "filters"),
        ("", "filters"),
        (0, "filters"),
        (False, "filters"),
    ],
)
def test_runs_reject_invalid_filters(filters: Any, error_path: str) -> None:
    service_api = mock.MagicMock()

    with pytest.raises(ValueError) as exc_info:
        Runs(service_api, "entity", "project", filters=filters)

    assert error_path in str(exc_info.value)
    service_api.execute_graphql.assert_not_called()


@pytest.mark.parametrize(
    "filters",
    [
        None,
        {},
        {"tags": "sgd"},
        {"tags": ["sgd", "test"]},
        {"tags": ("sgd", "test")},
        {"tags": []},
        {"tags": ()},
        {"tags": {"$all": ["sgd", "test"], "$nin": ["test-2"]}},
        {"tags": {"$in": ("sgd", "test"), "$all": (), "$nin": []}},
        {
            "$and": [
                {"tags": {"$all": ["sgd"]}},
                {"$or": ({"group": {"$in": ["group-1"]}},)},
                {"$nor": [{"state": "failed"}]},
            ]
        },
        {"$and": [], "$or": (), "$nor": []},
        {
            "config.options": {"tags": {"$all": [["literal"]]}},
            "summary_metrics.values": {"$in": [[1, 2], [3, 4]]},
            "config.query": {"$or": "literal"},
        },
        {"tags": {"$exists": True}, "$futureOperator": {"value": [1, 2]}},
        {"group": {"$in": [["group-1"]]}},
    ],
)
def test_runs_preserve_valid_filters(filters: dict[str, Any] | None) -> None:
    service_api = mock.MagicMock()
    service_api.execute_graphql.return_value = {
        "project": {
            "runCount": 0,
            "runs": {"edges": [], "pageInfo": {"hasNextPage": False}},
        }
    }
    original_filters = deepcopy(filters)

    runs = Runs(service_api, "entity", "project", filters=filters)

    assert list(runs) == []
    service_api.execute_graphql.assert_called_once()
    variables = service_api.execute_graphql.call_args.args[1]
    assert variables["filters"] == json.dumps(
        {} if original_filters is None else original_filters
    )
    assert filters == original_filters


def _make_upload_run(mocker, *, feature_enabled: bool):
    service_api = mocker.MagicMock()
    service_api.feature_enabled.return_value = feature_enabled
    service_api.execute_graphql.return_value = {
        "createRunFiles": {
            "runID": "run-node-id",
            "uploadHeaders": ["X-Test:test"],
            "files": [{"name": "model.bin", "uploadUrl": "https://storage/model.bin"}],
        }
    }
    run = Run(
        service_api=service_api,
        entity="entity",
        project="project",
        run_id="run-id",
        attrs={"name": "run-id", "state": "finished"},
    )
    mocker.patch("wandb.apis.public.runs.public.Files", return_value=["file-obj"])
    return service_api, run


def test_upload_file_marks_file_uploaded_when_supported(mocker, tmp_path):
    """upload_file sends a MarkRunFilesUploadedRequest when the server supports it."""
    service_api, run = _make_upload_run(mocker, feature_enabled=True)

    f = tmp_path / "model.bin"
    f.write_text("hello")
    run.upload_file(str(f), root=str(tmp_path))

    upload, notify = [c.args[0] for c in service_api.send_api_request.call_args_list]
    assert upload.WhichOneof("request") == "upload_file_request"
    assert upload.upload_file_request.url == "https://storage/model.bin"
    assert upload.upload_file_request.path == str(f)
    assert upload.upload_file_request.headers["X-Test"] == "test"
    assert notify.WhichOneof("request") == "mark_run_files_uploaded_request"
    notify = notify.mark_run_files_uploaded_request
    assert notify.entity == "entity"
    assert notify.project == "project"
    assert notify.run_id == "run-id"
    assert list(notify.files) == ["model.bin"]


def test_upload_file_skips_notification_when_unsupported(mocker, tmp_path):
    """Without the MARK_RUN_FILES_UPLOADED feature, no notification is sent."""
    service_api, run = _make_upload_run(mocker, feature_enabled=False)

    f = tmp_path / "model.bin"
    f.write_text("hello")
    run.upload_file(str(f), root=str(tmp_path))

    service_api.send_api_request.assert_called_once()
    request = service_api.send_api_request.call_args.args[0]
    assert request.WhichOneof("request") == "upload_file_request"


def test_stop_sends_stop_run_request(mocker):
    """stop() sends a StopRunRequest with the run's storage ID."""
    service_api = mocker.MagicMock()
    service_api.send_api_request.return_value = apb.ApiResponse(
        stop_run_response=apb.StopRunResponse()
    )
    run = Run(
        service_api=service_api,
        entity="entity",
        project="project",
        run_id="run-id",
        attrs={"name": "run-id", "id": "run-node-id", "state": "running"},
    )

    run.stop()

    service_api.send_api_request.assert_called_once()
    request = service_api.send_api_request.call_args.args[0]
    assert request.WhichOneof("request") == "stop_run_request"
    assert request.stop_run_request.storage_id == "run-node-id"


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("config", '{"test": "test"}', {"test": "test"}),
        ("summaryMetrics", '{"test": "test"}', {"test": "test"}),
        ("systemMetrics", '{"test": "test"}', {"test": "test"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_string_attrs(field, value, expected):
    api = wandb.Api()
    run = wandb.apis.public.Run(
        service_api=api._service_api,
        entity="test",
        project="test",
        run_id="test",
        attrs={field: value},
    )
    assert getattr(run, field) == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("config", {"test": "test"}),
        ("summaryMetrics", {"test": "test"}),
        ("systemMetrics", {"test": "test"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary_attrs_already_parsed(field, value):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        api = wandb.Api()
        run = wandb.apis.public.Run(
            service_api=api._service_api,
            entity="test",
            project="test",
            run_id="test",
            attrs={field: value},
        )
        assert getattr(run, field) == value


def test_run_metadata_downloads_through_service_api(mocker):
    service_api = mocker.MagicMock()
    run = Run(
        service_api=service_api,
        entity="entity",
        project="project",
        run_id="run-id",
        attrs={"name": "run-id", "state": "finished"},
    )
    file = mocker.MagicMock(url="https://files.example/wandb-metadata.json", size=17)
    mocker.patch.object(run, "file", return_value=file)

    def send_api_request(request: apb.ApiRequest) -> apb.ApiResponse:
        with open(request.download_file_request.path, "wb") as f:
            f.write(b'{"os":"Linux"}')
        return apb.ApiResponse(download_file_response=apb.DownloadFileResponse())

    service_api.send_api_request.side_effect = send_api_request

    assert run.metadata == {"os": "Linux"}
    request = service_api.send_api_request.call_args.args[0].download_file_request
    assert request.url == "https://files.example/wandb-metadata.json"
    assert request.size == 17


@pytest.mark.parametrize(
    "field,value",
    [
        ("config", 1),
        ("summaryMetrics", 1),
        ("systemMetrics", 1),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary__throws_type_error(field, value):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        api = wandb.Api()
        with pytest.raises(wandb.errors.CommError):
            wandb.apis.public.Run(
                service_api=api._service_api,
                entity="test",
                project="test",
                run_id="test",
                attrs={
                    field: value,
                },
            )


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("config", '{"test": "test\ttest"}', {"test": "test\ttest"}),
        ("summaryMetrics", '{"test": "test\ttest"}', {"test": "test\ttest"}),
        ("systemMetrics", '{"test": "test\ttest"}', {"test": "test\ttest"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_control_characters(field, value, expected):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        api = wandb.Api()
        run = wandb.apis.public.Run(
            service_api=api._service_api,
            entity="test",
            project="test",
            run_id="test",
            attrs={field: value},
        )
        assert getattr(run, field) == expected


def _make_lightweight_attrs():
    """Attrs matching LIGHTWEIGHT_RUN_FRAGMENT (no config/summary/system)."""
    return {
        "id": "abc123storeid",
        "tags": [],
        "name": "run-abc123",
        "displayName": "happy-fox-42",
        "sweepName": None,
        "state": "finished",
        "group": None,
        "jobType": None,
        "commit": None,
        "readOnly": False,
        "createdAt": "2026-03-24T01:00:00Z",
        "heartbeatAt": "2026-03-24T02:00:00Z",
        "description": "",
        "notes": "",
        "historyLineCount": 100,
        "user": {"name": "testuser", "username": "testuser"},
    }


def _make_full_response(lightweight_attrs):
    """Server response for a single-run query with RUN_FRAGMENT."""
    return {
        "project": {
            "run": {
                **lightweight_attrs,
                "config": json.dumps(
                    {
                        "learning_rate": {"value": 0.001},
                        "batch_size": {"value": 32},
                        "_wandb": {"value": {"t": {"1": [1, 2, 3]}}},
                    }
                ),
                "systemMetrics": "{}",
                "summaryMetrics": '{"loss": 0.5}',
                "historyKeys": "{}",
            }
        }
    }


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_lazy_run_config_triggers_full_load():
    """run.config on a lazy run should trigger load_full_data and return config."""
    service_api = mock.MagicMock()
    lightweight = _make_lightweight_attrs()
    service_api.execute_graphql.return_value = _make_full_response(lightweight)

    run = Run(
        service_api=service_api,
        entity="test-entity",
        project="test-project",
        run_id="run-abc123",
        attrs=dict(lightweight),
        lazy=True,
    )

    assert run._lazy is True
    assert run._full_data_loaded is False
    assert "config" not in run._attrs

    config = run.config

    assert run._full_data_loaded is True
    assert config == {"learning_rate": 0.001, "batch_size": 32}
    assert "_wandb" not in config
    service_api.execute_graphql.assert_called_once()


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_lazy_run_user_accessible_without_full_load():
    """run.user should work on lazy runs without triggering a full data load."""
    service_api = mock.MagicMock()
    lightweight = _make_lightweight_attrs()

    run = Run(
        service_api=service_api,
        entity="test-entity",
        project="test-project",
        run_id="run-abc123",
        attrs=dict(lightweight),
        lazy=True,
    )

    assert run._full_data_loaded is False
    user = run.user
    assert user.name == "testuser"
    assert run._full_data_loaded is False


def test_run_url_encodes_spaces_in_project_name():
    service_api = mock.MagicMock()
    service_api.app_url = "https://wandb.ai/"

    run = Run(
        service_api=service_api,
        entity="my-entity",
        project="My Project",
        run_id="12345",
        attrs={"name": "test"},
    )

    assert run.url == "https://wandb.ai/my-entity/My%20Project/runs/12345"


def _make_sweep_graphql_response(sweep_name: str) -> dict:
    return {
        "project": {
            "sweep": {
                "name": sweep_name,
                "state": "RUNNING",
                "config": "method: grid\n",
            }
        }
    }


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_sweep_property_loads_from_api():
    """Accessing run.sweep should fetch and return a Sweep from the API."""
    service_api = mock.MagicMock()
    lightweight = _make_lightweight_attrs()
    sweep_name = "test-sweep"
    lightweight["sweepName"] = sweep_name
    service_api.execute_graphql.return_value = _make_sweep_graphql_response(sweep_name)

    run = Run(
        service_api=service_api,
        entity="test-entity",
        project="test-project",
        run_id="run-abc123",
        attrs=dict(lightweight),
        lazy=True,
    )

    service_api.execute_graphql.assert_not_called()

    sweep = run.sweep

    assert isinstance(sweep, Sweep)
    assert sweep.name == sweep_name
    assert sweep.entity == "test-entity"
    assert sweep.project == "test-project"
    service_api.execute_graphql.assert_called_once()
    assert (
        service_api.execute_graphql.call_args.kwargs["variables"]["name"] == sweep_name
    )


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_lazy_run_missing_raises():
    service_api = mock.MagicMock()
    service_api.execute_graphql.return_value = {"project": {"run": None}}

    run = Run(
        service_api=service_api,
        entity="test-entity",
        project="test-project",
        run_id="run-abc123",
        attrs=dict(_make_lightweight_attrs()),
        lazy=True,
    )

    with pytest.raises(RunNotFoundError, match="Could not find run"):
        # run.config triggers a full data load
        _ = run.config
