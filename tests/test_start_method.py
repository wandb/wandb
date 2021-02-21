"""
start method tests.
"""

import platform
import sys

import six
import pytest
import wandb


@pytest.fixture
def run_full(live_mock_server, parse_ctx):
    """Test basic operation end to end."""

    def fn(settings=None):
        run = wandb.init(settings=settings)
        run.log(dict(val=1))
        run.finish()
        ctx_util = parse_ctx(live_mock_server.get_ctx())
        summary = ctx_util.summary
        assert six.viewitems(dict(val=1)) <= six.viewitems(summary)
        # TODO(jhr): check history and other things

        # return ctx_util for more specific checks in test
        return ctx_util

    yield fn


def test_default(run_full):
    cu = run_full()

    # py27 doesnt set start_method telemetry
    if sys.version_info >= (3, 0):
        telemetry = cu.telemetry
        assert telemetry and 5 in telemetry.get("8", [])


def test_junk(run_full):
    with pytest.raises(TypeError):
        run_full(settings=wandb.Settings(start_method="junk"))


@pytest.mark.skipif(sys.version_info < (3, 0), reason="py27 has no mp context")
def test_spawn(run_full):
    cu = run_full(settings=wandb.Settings(start_method="spawn"))
    telemetry = cu.telemetry
    assert telemetry and 5 in telemetry.get("8", [])


@pytest.mark.skipif(sys.version_info < (3, 0), reason="py27 has no mp context")
@pytest.mark.skipif(platform.system() == "Windows", reason="win has no fork")
def test_fork(run_full):
    cu = run_full(settings=wandb.Settings(start_method="fork"))
    telemetry = cu.telemetry
    assert telemetry and 6 in telemetry.get("8", [])


@pytest.mark.skipif(sys.version_info < (3, 0), reason="py27 has no mp context")
@pytest.mark.skipif(platform.system() == "Windows", reason="win has no forkserver")
def test_forkserver(run_full):
    cu = run_full(settings=wandb.Settings(start_method="forkserver"))
    telemetry = cu.telemetry
    assert telemetry and 7 in telemetry.get("8", [])


def test_thread(run_full):
    cu = run_full(settings=wandb.Settings(start_method="thread"))
    telemetry = cu.telemetry
    assert telemetry and 8 in telemetry.get("8", [])
