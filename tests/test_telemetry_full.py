"""
telemetry full tests.
"""

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
