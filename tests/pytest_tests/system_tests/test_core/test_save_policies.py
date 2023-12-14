import os
import time

import pytest
from wandb.filesync.dir_watcher import PolicyLive


@pytest.fixture
def mocked_live_policy(monkeypatch, wandb_init):
    run = wandb_init()
    fpath = os.path.join(run.dir, "test_file")
    with open(fpath, "w") as fp:
        fp.write("")

    live_policy = PolicyLive(fpath, "saved_file", None, None)

    def spoof_save(live_policy):
        live_policy._last_sync = os.path.getmtime(live_policy.file_path)
        live_policy._last_uploaded_time = time.time()
        live_policy._last_uploaded_size = live_policy.current_size

    def spoof_min_wait_for_size(live_policy, size):
        return 1

    monkeypatch.setattr(PolicyLive, "save_file", spoof_save)
    monkeypatch.setattr(PolicyLive, "min_wait_for_size", spoof_min_wait_for_size)
    monkeypatch.setattr(PolicyLive, "RATE_LIMIT_SECONDS", 1)

    live_policy._last_uploaded_time = time.time() - 60
    yield live_policy
    run.finish()


def test_policy_on_modified(mocked_live_policy):
    # policy does not save empty files
    mocked_live_policy.on_modified()
    curr_time = time.time()
    assert mocked_live_policy._last_uploaded_size == 0
    assert mocked_live_policy._last_uploaded_time < curr_time

    curr_time = time.time()
    # initialize _last_uploaded_size and _last_uploaded_time
    # mocked_live_policy.save_file()
    time.sleep(1.1)
    with open(mocked_live_policy.file_path, "w") as fp:
        fp.write("a" * 1000)
    mocked_live_policy.on_modified()
    # policy saves a file if enough time has passed
    assert mocked_live_policy._last_uploaded_time > curr_time


def test_policy_on_modified_rate_limited(mocked_live_policy):
    mocked_live_policy.save_file()
    first_upload_time = mocked_live_policy._last_uploaded_time
    with open(mocked_live_policy.file_path, "w") as fp:
        fp.write("a" * 1000)
        fp.close()
    # policy does not save a file if not enough time has passed
    mocked_live_policy.on_modified()
    assert mocked_live_policy._last_uploaded_time == first_upload_time
    assert mocked_live_policy._last_uploaded_size == 0


def test_policy_on_modified_size_rate_limited(mocked_live_policy):
    with open(mocked_live_policy.file_path, "w") as fp:
        fp.write("a" * 10)
        fp.close()
    mocked_live_policy.save_file()
    first_upload_time = mocked_live_policy._last_uploaded_time
    time.sleep(1.1)
    with open(mocked_live_policy.file_path, "w") as fp:
        fp.write("a" * 11)
        fp.close()
    # policy does not save a file if file change size not large enough
    mocked_live_policy.on_modified()
    assert mocked_live_policy._last_uploaded_time == first_upload_time
    assert mocked_live_policy._last_uploaded_size == 10


def test_live_policy_policy(mocked_live_policy):
    assert mocked_live_policy.policy == "live"
