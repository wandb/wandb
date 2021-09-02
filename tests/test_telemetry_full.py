"""
telemetry full tests.
"""
import platform

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
def test_telemetry_imports_jax(live_mock_server, parse_ctx):
    import jax

    wandb.init()
    wandb.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry

    # jax in finish modules but not in init modules
    assert telemetry and 12 in telemetry.get("1", [])
    assert telemetry and 12 in telemetry.get("2", [])


def test_telemetry_set_in_wandb_init(live_mock_server, parse_ctx):
    wandb.init(name="test_name", tags=["my-tag"], config={"abc": 123}, id="mynewid")
    wandb.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry

    # jax in finish modules but not in init modules
    assert telemetry and 11 in telemetry.get("3", [])  # name
    assert telemetry and 12 in telemetry.get("3", [])  # id
    assert telemetry and 13 in telemetry.get("3", [])  # tags
    assert telemetry and 14 in telemetry.get("3", [])  # config
