import re

import pytest
import wandb
from wandb.testing.relay import TokenizedCircularPattern


def log_line_match_http_error(user, project, run_id, status_code):
    pattern = (
        r"POST http://127\.0\.0\.1:\d+/files/"
        + re.escape(user)
        + "/"
        + re.escape(project)
        + "/"
        + re.escape(run_id)
        + r"/file_stream \(status: "
        + re.escape(status_code)
        + r"\): retrying in \d+\.\d+s \(\d+ left\)"
    )
    return re.compile(pattern)


def log_line_match_eof(user, project, run_id):
    pattern = (
        r"POST http://127\.0\.0\.1:\d+/files/"
        + re.escape(user)
        + "/"
        + re.escape(project)
        + "/"
        + re.escape(run_id)
        + r"/file_stream: retrying in \d+\.\d+s \(\d+ left\)"
    )
    return re.compile(pattern)


@pytest.mark.wandb_core_only
@pytest.mark.parametrize("status_code", [429, 500])
def test_retryable_codes(
    status_code,
    user,
    test_settings,
    relay_server,
    inject_file_stream_response,
    monkeypatch,
):
    # turn on debug logs
    monkeypatch.setenv("WANDB_DEBUG", "true")
    monkeypatch.setenv("WANDB_CORE_DEBUG", "true")

    with relay_server() as relay:
        run = wandb.init(
            settings=test_settings(
                {
                    "_file_stream_retry_wait_min_seconds": 1,
                    "_disable_machine_info": True,
                }
            )
        )
        relay.inject.append(
            inject_file_stream_response(
                run=run,
                application_pattern=(
                    TokenizedCircularPattern.APPLY_TOKEN
                    + TokenizedCircularPattern.APPLY_TOKEN
                    + TokenizedCircularPattern.STOP_TOKEN
                ),
                status=status_code,
                body="transient error",
            )
        )
        run.log({"acc": 1})
        run.finish()

    # check debug logs
    with open(run.settings.log_symlink_internal) as f:
        internal_log = f.read()
        regex_pattern = log_line_match_http_error(
            user, run.project, run.id, str(status_code)
        )
        matches = regex_pattern.findall(internal_log)
        # we should have 2 retries
        assert len(matches) == 2


@pytest.mark.wandb_core_only
@pytest.mark.parametrize(
    "status_code, name",
    [
        (400, "Bad Request"),
        (401, "Unauthorized"),
        (403, "Forbidden"),
        (404, "Not Found"),
        (409, "Conflict"),
        (410, "Gone"),
    ],
)
def test_non_retryable_codes(
    status_code,
    name,
    user,
    test_settings,
    relay_server,
    inject_file_stream_response,
    monkeypatch,
):
    # turn on debug logs
    monkeypatch.setenv("WANDB_DEBUG", "true")
    monkeypatch.setenv("WANDB_CORE_DEBUG", "true")

    with relay_server() as relay:
        run = wandb.init(
            settings=test_settings(
                {
                    "_file_stream_retry_wait_min_seconds": 1,
                    "_disable_machine_info": True,
                }
            )
        )
        relay.inject.append(
            inject_file_stream_response(
                run=run,
                application_pattern=(
                    TokenizedCircularPattern.APPLY_TOKEN
                    + TokenizedCircularPattern.STOP_TOKEN
                ),
                status=status_code,
                body="non-retryable error",
            )
        )
        run.log({"acc": 1})
        run.finish()

    # check debug logs
    with open(run.settings.log_symlink_internal) as f:
        internal_log = f.read()
        log_line = f"filestream: failed to upload: {status_code} {name.upper()}"
        assert log_line in internal_log


@pytest.mark.wandb_core_only
def test_connection_reset(
    user,
    test_settings,
    relay_server,
    inject_file_stream_connection_reset,
    monkeypatch,
):
    # turn on debug logs
    monkeypatch.setenv("WANDB_DEBUG", "true")
    monkeypatch.setenv("WANDB_CORE_DEBUG", "true")

    with relay_server() as relay:
        run = wandb.init(
            settings=test_settings(
                {
                    "_file_stream_retry_wait_min_seconds": 1,
                    "_disable_machine_info": True,
                }
            )
        )
        relay.inject.append(
            inject_file_stream_connection_reset(
                run=run,
                application_pattern=(
                    TokenizedCircularPattern.APPLY_TOKEN
                    + TokenizedCircularPattern.APPLY_TOKEN
                    + TokenizedCircularPattern.STOP_TOKEN
                ),
                body=ConnectionResetError("Connection reset by peer"),
            )
        )
        run.log({"acc": 1})
        run.finish()

    with open(run.settings.log_symlink_internal) as f:
        internal_log = f.read()
        regex_pattern = log_line_match_eof(user, run.project, run.id)
        matches = regex_pattern.findall(internal_log)
        # we should have 2 retries
        assert len(matches) == 2
        # assert we see EOF in the logs twice
        assert internal_log.count(': EOF"') == 2
