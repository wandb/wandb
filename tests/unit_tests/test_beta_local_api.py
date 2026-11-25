from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from unittest import mock

import pytest
from wandb.beta import LocalApi, LocalRun
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk import wandb_setup

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


def test_local_reads_do_not_require_identity_token(tmp_path, monkeypatch):
    setup = wandb_setup.singleton()
    token_file = str(tmp_path / "missing.jwt")
    monkeypatch.setattr(setup.settings, "identity_token_file", token_file)
    connection = mock.MagicMock()
    connection.api_init_request.return_value = apb.ServerApiInitResponse(api_id="local")
    connection.api_request.return_value = apb.ApiResponse(
        list_local_runs_response=apb.ListLocalRunsResponse()
    )

    with mock.patch.object(setup, "ensure_service", return_value=connection):
        assert LocalApi(tmp_path).runs() == []

    settings = connection.api_init_request.call_args.args[0]
    assert not settings.HasField("identity_token_file")
    assert setup.settings.identity_token_file == token_file


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


def test_history_follows_pages(tmp_path):
    service_api = mock.MagicMock()
    service_api.send_api_request.side_effect = [
        apb.ApiResponse(
            read_local_run_history_response=apb.ReadLocalRunHistoryResponse(
                rows=b'{"_step":3,"loss":0.25}\n{"_step":4,"a.b":"x"}\n',
                next_offset=512,
            )
        ),
        apb.ApiResponse(
            read_local_run_history_response=apb.ReadLocalRunHistoryResponse(
                rows=b'{"_step":5,"loss":NaN}\n'
            )
        ),
    ]
    run = LocalRun(service_api, info=_info(tmp_path))

    rows = list(run.history(keys=["loss", "a.b"], min_step=3))

    assert rows[:2] == [{"_step": 3, "loss": 0.25}, {"_step": 4, "a.b": "x"}]
    assert rows[2]["loss"] != rows[2]["loss"]
    first, second = (
        call.args[0].read_local_run_history_request
        for call in service_api.send_api_request.call_args_list
    )
    assert (list(first.keys), first.min_step, first.offset) == (["loss", "a.b"], 3, 0)
    assert second.offset == 512
    assert first.limit == second.limit > 0


def test_history_dataframes(tmp_path):
    pl = pytest.importorskip("polars")
    service_api = mock.MagicMock()
    service_api.send_api_request.return_value = apb.ApiResponse(
        read_local_run_history_response=apb.ReadLocalRunHistoryResponse(
            rows=b'{"_step":0,"loss":1.0}\n{"_step":1,"loss":NaN,"acc":0.5}\n'
        )
    )
    history = LocalRun(service_api, info=_info(tmp_path)).history()

    pandas_df = history.to_pandas()
    assert list(pandas_df.columns) == ["_step", "loss", "acc"]
    assert pandas_df["acc"].isna().tolist() == [True, False]

    polars_df = history.to_polars()
    assert polars_df.schema == {
        "_step": pl.Int64,
        "loss": pl.Float64,
        "acc": pl.Float64,
    }
    assert polars_df["acc"].to_list() == [None, 0.5]


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
