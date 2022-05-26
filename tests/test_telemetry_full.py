"""
telemetry full tests.
"""
import platform
import sys
from unittest import mock

import pytest
import wandb


def test_telemetry_finish(runner, live_mock_server, parse_ctx):
    with runner.isolated_filesystem():
        run = wandb.init()
        run.finish()

        ctx_util = parse_ctx(live_mock_server.get_ctx())
        telemetry = ctx_util.telemetry

        assert telemetry and 2 in telemetry.get("3", [])


def test_telemetry_imports_hf(runner, live_mock_server, parse_ctx):
    with runner.isolated_filesystem():
        run = wandb.init()

        with mock.patch.dict("sys.modules", {"transformers": mock.Mock()}):
            import transformers

            run.finish()

            ctx_util = parse_ctx(live_mock_server.get_ctx())
            telemetry = ctx_util.telemetry

            # hf in finish modules but not in init modules
            assert telemetry and 11 not in telemetry.get("1", [])
            assert telemetry and 11 in telemetry.get("2", [])


def test_telemetry_imports_catboost(runner, live_mock_server, parse_ctx):
    with runner.isolated_filesystem():
        with mock.patch.dict("sys.modules", {"catboost": mock.Mock()}):
            import catboost

            run = wandb.init()
            run.finish()

            ctx_util = parse_ctx(live_mock_server.get_ctx())
            telemetry = ctx_util.telemetry

            # catboost in both init and finish modules
            assert telemetry and 7 in telemetry.get("1", [])
            assert telemetry and 7 in telemetry.get("2", [])


@pytest.mark.skipif(
    platform.system() == "Windows", reason="test suite does not build jaxlib on windows"
)
@pytest.mark.skipif(sys.version_info >= (3, 10), reason="jax has no py3.10 wheel")
def test_telemetry_imports_jax(runner, live_mock_server, parse_ctx):
    with runner.isolated_filesystem():
        import jax

        wandb.init()
        wandb.finish()

        ctx_util = parse_ctx(live_mock_server.get_ctx())
        telemetry = ctx_util.telemetry

        # jax in finish modules but not in init modules
        assert telemetry and 12 in telemetry.get("1", [])
        assert telemetry and 12 in telemetry.get("2", [])


def test_telemetry_run_organizing_init(runner, live_mock_server, parse_ctx):
    with runner.isolated_filesystem():
        wandb.init(name="test_name", tags=["my-tag"], config={"abc": 123}, id="mynewid")
        wandb.finish()

        ctx_util = parse_ctx(live_mock_server.get_ctx())
        telemetry = ctx_util.telemetry

        assert telemetry and 13 in telemetry.get("3", [])  # name
        assert telemetry and 14 in telemetry.get("3", [])  # id
        assert telemetry and 15 in telemetry.get("3", [])  # tags
        assert telemetry and 16 in telemetry.get("3", [])  # config


def test_telemetry_run_organizing_set(runner, live_mock_server, parse_ctx):
    with runner.isolated_filesystem():
        run = wandb.init()
        run.name = "test-name"
        run.tags = ["tag1"]
        wandb.config.update = True
        run.finish()

        ctx_util = parse_ctx(live_mock_server.get_ctx())
        telemetry = ctx_util.telemetry

        assert telemetry and 17 in telemetry.get("3", [])  # name
        assert telemetry and 18 in telemetry.get("3", [])  # tags
        assert telemetry and 19 in telemetry.get("3", [])  # config update
