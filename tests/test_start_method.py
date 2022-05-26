"""
start method tests.
"""

import platform
import sys

import pytest
import wandb
from wandb.errors import UsageError


@pytest.fixture
def run_full(live_mock_server, parse_ctx):
    """Test basic operation end to end."""

    def fn(settings=None):
        run = wandb.init(settings=settings)
        run.log(dict(val=1))
        run.finish()
        ctx_util = parse_ctx(live_mock_server.get_ctx())
        summary = ctx_util.summary
        assert dict(val=1).items() <= dict.items(summary)
        # TODO(jhr): check history and other things

        # return ctx_util for more specific checks in test
        return ctx_util

    yield fn


def test_default(run_full):
    cu = run_full()
    telemetry = cu.telemetry
    assert telemetry and 5 in telemetry.get("8", [])


def test_junk(run_full):
    with pytest.raises(UsageError):
        run_full(settings=dict(start_method="junk"))


def test_spawn(run_full):
    # note: passing in dict to settings (here and below)
    # since this will set start_method with source=Source.INIT
    cu = run_full(settings=dict(start_method="spawn"))
    telemetry = cu.telemetry
    assert telemetry and 5 in telemetry.get("8", [])


@pytest.mark.skipif(platform.system() == "Windows", reason="win has no fork")
def test_fork(run_full):
    cu = run_full(settings=dict(start_method="fork"))
    telemetry = cu.telemetry
    assert telemetry and 6 in telemetry.get("8", [])


@pytest.mark.skipif(platform.system() == "Windows", reason="win has no forkserver")
def test_forkserver(run_full):
    cu = run_full(settings=dict(start_method="forkserver"))
    telemetry = cu.telemetry
    assert telemetry and 7 in telemetry.get("8", [])


def test_thread(run_full):
    cu = run_full(settings=dict(start_method="thread"))
    telemetry = cu.telemetry
    assert telemetry and 8 in telemetry.get("8", [])
