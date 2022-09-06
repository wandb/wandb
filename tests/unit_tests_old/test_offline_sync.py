import glob
import os
import subprocess
import sys
import time

import pytest

from tests.unit_tests_old import utils


@pytest.mark.flaky
@pytest.mark.xfail(reason="flaky test")
def test_sync_in_progress(live_mock_server, test_dir):
    with open("train.py", "w") as f:
        f.write(utils.fixture_open("train.py").read())
    env = dict(os.environ)
    env["WANDB_MODE"] = "offline"
    env["WANDB_DIR"] = test_dir
    env["WANDB_CONSOLE"] = "off"
    stdout = open("stdout.log", "w+")
    offline_run = subprocess.Popen(
        [
            sys.executable,
            "train.py",
            "--epochs",
            "50",
            "--sleep_every",
            "15",
            "--heavy",
        ],
        stdout=stdout,
        stderr=subprocess.STDOUT,
        bufsize=1,
        close_fds=True,
        env=env,
    )
    attempts = 0
    latest_run = os.path.join(test_dir, "wandb", "latest-run")
    while not os.path.exists(latest_run) and attempts < 50:
        time.sleep(0.1)
        # On windows we have no symlinks, so we grab the run dir
        if attempts > 0 and attempts % 10 == 0:
            if os.path.exists(os.path.join(test_dir, "wandb")):
                run_dir = os.listdir(os.path.join(test_dir, "wandb"))
                if len(run_dir) > 0:
                    latest_run = os.path.join(test_dir, "wandb", run_dir[0])
        attempts += 1
    if attempts == 50:
        print("cur dir contents: ", os.listdir(test_dir))
        print("wandb dir contents: ", os.listdir(os.path.join(test_dir, "wandb")))
        stdout.seek(0)
        print("STDOUT")
        print(stdout.read())
        debug = os.path.join("wandb", "debug.log")
        debug_int = os.path.join("wandb", "debug-internal.log")
        if os.path.exists(debug):
            print("DEBUG")
            print(open(debug).read())
        if os.path.exists(debug_int):
            print("DEBUG INTERNAL")
            print(open(debug).read())
        assert False, "train.py failed to launch :("
    else:
        print(
            "Starting live syncing after {} seconds from: {}".format(
                attempts * 0.1, latest_run
            )
        )
    for i in range(3):
        # Generally, the first sync will fail because the .wandb file is empty
        sync = subprocess.Popen(["wandb", "sync", latest_run], env=os.environ)
        assert sync.wait() == 0
        # Only confirm we don't have a .synced file if our offline run is still running
        if offline_run.poll() is None:
            assert len(glob.glob(os.path.join(latest_run, "*.synced"))) == 0
    assert offline_run.wait() == 0
    sync = subprocess.Popen(["wandb", "sync", latest_run], env=os.environ)
    assert sync.wait() == 0
    assert len(glob.glob(os.path.join(latest_run, "*.synced"))) == 1
    print("Number of upserts: ", live_mock_server.get_ctx()["upsert_bucket_count"])
    assert live_mock_server.get_ctx()["upsert_bucket_count"] >= 3
