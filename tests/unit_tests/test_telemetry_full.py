"""
telemetry full tests.
"""
import platform
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


@pytest.mark.parametrize(
    "module, telemetry_value",
    [
        ("transformers", 11),
        ("catboost", 7),
        ("jax", 12),
    ],
)
def test_telemetry_imports(
    runner, live_mock_server, parse_ctx, module, telemetry_value
):
    with runner.isolated_filesystem():

        module_mock = mock.MagicMock()
        module_mock.__name__ = module
        with mock.patch.dict("sys.modules", {module: module_mock}):
            run = wandb.init()
            __import__(module)
            run.finish()

        ctx_util = parse_ctx(live_mock_server.get_ctx())
        telemetry = ctx_util.telemetry

        assert telemetry and telemetry_value in telemetry.get("2", [])

        with mock.patch.dict("sys.modules", {module: module_mock}):
            __import__(module)
            run = wandb.init()
            run.finish()

        ctx_util = parse_ctx(live_mock_server.get_ctx())
        telemetry = ctx_util.telemetry

        assert telemetry and telemetry_value in telemetry.get("2", [])


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
