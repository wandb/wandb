import json
from unittest import mock

import pytest
import wandb
from wandb.apis.public.runs import Run, RunNotFoundError
from wandb.apis.public.sweeps import Sweep
from wandb.proto import wandb_api_pb2 as apb


def _make_upload_run(mocker, *, feature_enabled: bool):
    service_api = mocker.MagicMock()
    service_api.feature_enabled.return_value = feature_enabled
    run = Run(
        service_api=service_api,
        entity="entity",
        project="project",
        run_id="run-id",
        attrs={"name": "run-id", "state": "finished"},
    )
    # Stub the byte-upload (InternalApi.push) and the returned File lookup.
    mocker.patch("wandb.apis.public.runs.InternalApi")
    mocker.patch("wandb.apis.public.runs.public.Files", return_value=["file-obj"])
    return service_api, run


def test_upload_file_marks_file_uploaded_when_supported(mocker, tmp_path):
    """upload_file sends a MarkRunFilesUploadedRequest when the server supports it."""
    service_api, run = _make_upload_run(mocker, feature_enabled=True)

    f = tmp_path / "model.bin"
    f.write_text("hello")
    run.upload_file(str(f), root=str(tmp_path))

    service_api.send_api_request.assert_called_once()
    request = service_api.send_api_request.call_args.args[0]
    assert request.WhichOneof("request") == "mark_run_files_uploaded_request"
    notify = request.mark_run_files_uploaded_request
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

    service_api.send_api_request.assert_not_called()


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
