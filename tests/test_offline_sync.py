import os
import subprocess
import time
import glob
from .utils import fixture_open


def test_sync_in_progress(live_mock_server):
    with open("train.py", "w") as f:
        f.write(fixture_open("train.py").read())
    env = dict(os.environ)
    env["WANDB_MODE"] = "offline"
    offline_run = subprocess.Popen(
        ["python", "train.py", "--epochs", "50", "--sleep_every", "15", "--heavy"],
        env=env,
    )
    attempts = 0
    latest_run = os.path.join("wandb", "latest-run")
    while not os.path.exists(latest_run) and attempts < 20:
        time.sleep(0.1)
        attempts += 1
    sync_file = ".wandb"
    for i in range(3):
        # Generally, the first sync will fail because the .wandb file is empty
        sync = subprocess.Popen(
            ["wandb", "sync", latest_run], env=os.environ
        )
        assert sync.wait() == 0
        matches = glob.glob(os.path.join(latest_run, "*.wandb"))
        if len(matches) > 0:
            sync_file = matches[0]
        assert not os.path.exists(os.path.join(sync_file + ".synced"))
    assert offline_run.wait() == 0
    sync = subprocess.Popen(
        ["wandb", "sync", latest_run], env=os.environ
    )
    assert sync.wait() == 0
    assert os.path.exists(os.path.join(sync_file + ".synced"))
    print("Number of upserts: ", live_mock_server.get_ctx()["upsert_bucket_count"])
    assert live_mock_server.get_ctx()["upsert_bucket_count"] >= 3
