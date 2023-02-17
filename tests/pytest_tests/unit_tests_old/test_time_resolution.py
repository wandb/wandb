"""
time resolution full tests.
"""

import time

import wandb


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
