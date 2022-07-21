"""
time resolution full tests.
"""

import time

import wandb


def test_log(live_mock_server, test_settings, parse_ctx):
    """Make sure log is generating history with subsecond resolution."""

    before = time.time()
    with wandb.init(settings=test_settings) as run:
        for i in range(10):
            run.log(dict(k=i))
            time.sleep(0.000010)  # 10 us
    after = time.time()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    history = ctx_util.history

    assert len(history) == 10
    assert any([h["_timestamp"] % 1 > 0 for h in history])
    assert any([h["_runtime"] % 1 > 0 for h in history])
    assert all([before <= h["_timestamp"] <= after for h in history])
    assert all([0 <= h["_runtime"] <= after - before for h in history])


def test_stats(live_mock_server, test_settings, parse_ctx):
    test_settings.update(
        {"_stats_sample_rate_seconds": 0.6, "_stats_samples_to_average": 2}
    )

    before = time.time()
    with wandb.init(settings=test_settings) as _:
        time.sleep(8)
    after = time.time()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    stats = ctx_util.stats

    assert len(stats) > 1
    assert any([s["_timestamp"] % 1 > 0 for s in stats])
    assert any([s["_runtime"] % 1 > 0 for s in stats])
    assert all([before <= s["_timestamp"] <= after for s in stats])
    assert all([0 <= s["_runtime"] <= after - before for s in stats])


def test_resume(live_mock_server, test_settings, parse_ctx):
    live_mock_server.set_ctx({"resume": True})

    before = time.time()
    with wandb.init(settings=test_settings, resume="allow") as run:
        for i in range(10):
            run.log(dict(k=i))
            time.sleep(0.000010)  # 10 us
    after = time.time()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    history = ctx_util.history
    history_updates = ctx_util.get_filestream_file_updates()["wandb-history.jsonl"]

    assert history_updates[0]["offset"] == 15
    assert len([h for h in history if h]) == 10
    assert [h for h in history if h][0]["_step"] == 16
    assert any([h["_timestamp"] % 1 > 0 for h in history if h])
    assert any([h["_runtime"] % 1 > 0 for h in history if h])
    assert all([before <= h["_timestamp"] <= after for h in history if h])
    assert all([h["_runtime"] >= 70 for h in history if h])
