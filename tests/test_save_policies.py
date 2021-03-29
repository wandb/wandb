import time


def test_policy_on_modified(monkeypatch, wandb_init_run, mocked_live_policy):
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
        fp.close()
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
