"""
telemetry full tests.
"""
import platform
import sys

import pytest
import wandb

try:
    from unittest import mock
except ImportError:  # TODO: this is only for python2
    import mock


def test_telemetry_finish(live_mock_server, parse_ctx):
    run = wandb.init()
    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry

    # finish()
    assert telemetry and 2 in telemetry.get("3", [])


def test_telemetry_imports_hf(live_mock_server, parse_ctx):
    run = wandb.init()
    with mock.patch.dict("sys.modules", {"transformers": mock.Mock()}):
        import transformers

        run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry

    # hf in finish modules but not in init modules
    assert telemetry and 11 not in telemetry.get("1", [])
    assert telemetry and 11 in telemetry.get("2", [])


@pytest.mark.skipif(
    platform.system() == "Windows", reason="test suite does not build jaxlib on windows"
)
@pytest.mark.skipif(sys.version_info >= (3, 10), reason="jax has no py3.10 wheel")
def test_telemetry_imports_jax(live_mock_server, parse_ctx):
    import jax

    wandb.init()
    wandb.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry

    # jax in finish modules but not in init modules
    assert telemetry and 12 in telemetry.get("1", [])
    assert telemetry and 12 in telemetry.get("2", [])


def test_telemetry_run_organizing_init(live_mock_server, parse_ctx):
    wandb.init(name="test_name", tags=["my-tag"], config={"abc": 123}, id="mynewid")
    wandb.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry

    assert telemetry and 13 in telemetry.get("3", [])  # name
    assert telemetry and 14 in telemetry.get("3", [])  # id
    assert telemetry and 15 in telemetry.get("3", [])  # tags
    assert telemetry and 16 in telemetry.get("3", [])  # config


def test_telemetry_run_organizing_set(live_mock_server, parse_ctx):
    run = wandb.init()
    run.name = "test-name"
    run.tags = ["tag1"]
    wandb.config.update = True
    wandb.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry

    assert telemetry and 17 in telemetry.get("3", [])  # name
    assert telemetry and 18 in telemetry.get("3", [])  # tags
    assert telemetry and 19 in telemetry.get("3", [])  # config update
