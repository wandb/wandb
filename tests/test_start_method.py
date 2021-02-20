"""
start method tests.
"""

import platform

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
        # return ctx_util for more specific checks in test
        return ctx_util

    yield fn


def test_default(run_full):
    run_full()


def test_junk(run_full):
    with pytest.raises(TypeError):
        run_full(settings=wandb.Settings(start_method="junk"))


def test_spawn(run_full):
    run_full(settings=wandb.Settings(start_method="fork"))


@pytest.mark.skipif(platform.system() == "Windows")
def test_fork(run_full):
    run_full(settings=wandb.Settings(start_method="fork"))


@pytest.mark.skipif(platform.system() == "Windows")
def test_forkserver(run_full):
    run_full(settings=wandb.Settings(start_method="forkserver"))


def test_thread(run_full):
    # TODO(jhr): problem with thread and console. maybe redir threads?
    run_full(settings=wandb.Settings(start_method="thread", console="off"))


# TODO(jhr): enable this when console thread issue fixed
# def test_thread_broken(run_full):
#     run_full(settings=wandb.Settings(start_method="thread"))
