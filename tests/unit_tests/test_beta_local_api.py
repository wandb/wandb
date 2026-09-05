from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from unittest import mock

import pytest
from wandb.beta import LocalApi, LocalRun
from wandb.proto import wandb_api_pb2 as apb

RUN_DIR = "run-20260101_120000-abc"


def _info(tmp_path: pathlib.Path, **overrides) -> apb.LocalRunInfo:
    fields = {
        "wandb_file": str(tmp_path / RUN_DIR / "run-abc.wandb"),
        "run_id": "abc",
        "project": "proj",
        "display_name": "first",
        "tags": ["a"],
        "state": "finished",
    }
    fields.update(overrides)
    return apb.LocalRunInfo(**fields)


def _api(tmp_path: pathlib.Path, service_api) -> LocalApi:
    api = LocalApi(tmp_path)
    api._service_api = service_api
    return api


def test_runs_lists_the_directory(tmp_path):
    service_api = mock.MagicMock()
    service_api.send_api_request.return_value = apb.ApiResponse(
        list_local_runs_response=apb.ListLocalRunsResponse(runs=[_info(tmp_path)])
    )

    (run,) = _api(tmp_path, service_api).runs()

    request = service_api.send_api_request.call_args.args[0]
    assert request.list_local_runs_request.wandb_dir == str(tmp_path.resolve())
    assert (run.id, run.name, run.state, run.tags) == (
        "abc",
        "first",
        "finished",
        ["a"],
    )
    assert run.sync_dir == str(tmp_path / RUN_DIR)
    assert run.wandb_file == str(tmp_path / RUN_DIR / "run-abc.wandb")
    assert service_api.send_api_request.call_count == 1


def test_run_details_are_read_once_until_refresh(tmp_path):
    service_api = mock.MagicMock()
    service_api.send_api_request.return_value = apb.ApiResponse(
        read_local_run_response=apb.ReadLocalRunResponse(
            info=_info(tmp_path, state="running"),
            config_json='{"lr": 0.1, "_wandb": {"code_path": "train.py"}}',
            summary_json='{"loss": 0.5}',
            environment_json='{"os": "linux"}',
            last_step=9,
            history_keys=["loss"],
        )
    )
    run = LocalRun(service_api, wandb_file=str(tmp_path / RUN_DIR / "run-abc.wandb"))

    assert run.state == "running"
    assert run.config == {"lr": 0.1}
    assert run.summary == {"loss": 0.5}
    assert run.metadata == {"os": "linux"}
    assert run.last_step == 9
    assert run.history_keys == ["loss"]
    assert run.exit_code is None
    assert run.start_time is None
    assert service_api.send_api_request.call_count == 1

    run.refresh()
    assert run.name == "first"
    assert service_api.send_api_request.call_count == 2


def test_history_rows_are_decoded(tmp_path):
    service_api = mock.MagicMock()
    service_api.send_api_request.return_value = apb.ApiResponse(
        read_local_run_history_response=apb.ReadLocalRunHistoryResponse(
            rows=[
                apb.LocalHistoryRow(
                    step=3,
                    items=[
                        apb.LocalHistoryItem(key="loss", value_json="0.25"),
                        apb.LocalHistoryItem(key="name", value_json='"x"'),
                    ],
                )
            ]
        )
    )
    run = LocalRun(service_api, info=_info(tmp_path))

    rows = run.history(keys=["loss", "name"], last=1)

    assert rows == [{"_step": 3, "loss": 0.25, "name": "x"}]
    request = service_api.send_api_request.call_args.args[0]
    assert list(request.read_local_run_history_request.keys) == ["loss", "name"]
    assert request.read_local_run_history_request.last == 1
    assert not request.read_local_run_history_request.HasField("min_step")


def test_console_logs(tmp_path):
    service_api = mock.MagicMock()
    service_api.send_api_request.return_value = apb.ApiResponse(
        read_local_run_console_logs_response=apb.ReadLocalRunConsoleLogsResponse(
            lines=[
                apb.RunConsoleLogLine(
                    number=2,
                    timestamp="2026-01-01T12:00:00Z",
                    level="error",
                    content="line 2",
                )
            ],
            total_lines=3,
        )
    )
    run = LocalRun(service_api, info=_info(tmp_path))

    (line,) = run.console_logs(last=1)

    assert line.number == 2
    assert line.content == "line 2"
    assert line.level == "error"
    assert line.timestamp == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    request = service_api.send_api_request.call_args.args[0]
    assert request.read_local_run_console_logs_request.last == 1

    run.console_logs()
    request = service_api.send_api_request.call_args.args[0]
    assert not request.read_local_run_console_logs_request.HasField("last")


def test_run_resolves_paths_names_and_ids(tmp_path):
    wandb_file = tmp_path / RUN_DIR / "run-abc.wandb"
    wandb_file.parent.mkdir()
    wandb_file.touch()
    service_api = mock.MagicMock()
    api = _api(tmp_path, service_api)

    assert api.run(RUN_DIR).wandb_file == str(wandb_file)
    assert api.run(wandb_file).wandb_file == str(wandb_file)
    assert api.run(wandb_file.parent).wandb_file == str(wandb_file)
    assert api.run("abc").wandb_file == str(wandb_file)
    with pytest.raises(FileNotFoundError):
        api.run("nope")
    service_api.send_api_request.assert_not_called()
