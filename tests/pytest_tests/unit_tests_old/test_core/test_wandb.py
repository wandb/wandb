"""These test the high level sdk methods by mocking out the backend.
See wandb_integration_test.py for tests that launch a real backend against
a live backend server.
"""

import importlib
import os
import platform
import subprocess
import time

import pytest
import wandb
from tests.pytest_tests.unit_tests_old import utils


@pytest.mark.wandb_args(k8s=True)
def test_k8s_success(wandb_init_run):
    assert wandb.run._settings.docker == "test@sha256:1234"


@pytest.mark.wandb_args(k8s=False)
def test_k8s_failure(wandb_init_run):
    assert wandb.run._settings.docker is None


"""These test the full stack by launching a real backend server.  You won't get
credit for coverage of the backend logic in these tests.  See test_sender.py for testing
specific backend logic, or wandb_test.py for testing frontend logic.

Be sure to use `test_settings` or an isolated directory
"""

reloadFn = importlib.reload

# TODO: better debugging, if the backend process fails to start we currently
#  don't get any debug information even in the internal logs.  For now I'm writing
#  logs from all tests that use test_settings to tests/logs/TEST_NAME.  If you're
#  having tests just hang forever, I suggest running test/test_sender to see backend
#  errors until we ensure we propagate the errors up.


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="File syncing is somewhat busted in windows",
)
@pytest.mark.wandb_core_failure(feature="file_upload")
def test_parallel_runs(runner, live_mock_server, test_settings, test_name):
    with runner.isolation():
        with open("train.py", "w") as f:
            f.write(utils.fixture_open("train.py").read())
        p1 = subprocess.Popen(["python", "train.py"], env=os.environ)
        p2 = subprocess.Popen(["python", "train.py"], env=os.environ)
        exit_codes = [p.wait() for p in (p1, p2)]
        assert exit_codes == [0, 0]
        num_runs = 0
        # Assert we've stored 2 runs worth of files
        # TODO: not confirming output.log because it is missing sometimes likely due to a BUG
        # TODO: code saving sometimes doesnt work?
        run_files_sorted = sorted(
            [
                "config.yaml",
                f"code/tests/pytest_tests/unit_tests_old/logs/{test_name}/train.py",
                "requirements.txt",
                "wandb-metadata.json",
                "wandb-summary.json",
            ]
        )
        for run, files in live_mock_server.get_ctx()["storage"].items():
            print("Files from server", files)
            # artifacts are stored in the server storage as well so ignore them
            if run == "unknown":
                continue
            num_runs += 1
            target_files = run_files_sorted
            assert (
                sorted(
                    f
                    for f in files
                    if not f.endswith(".patch")
                    and not f.endswith("pt.trace.json")
                    and f != "output.log"
                )
                == target_files
            )
        assert num_runs == 2


@pytest.mark.wandb_core_failure(feature="file_upload")
def test_network_fault_files(live_mock_server, test_settings):
    live_mock_server.set_ctx({"fail_storage_times": 5})
    run = wandb.init(settings=test_settings)
    run.finish()
    ctx = live_mock_server.get_ctx()
    print(ctx)
    assert [
        f
        for f in sorted(ctx["storage"][run.id])
        if not f.endswith(".patch") and not f.endswith(".py")
    ] == sorted(
        [
            "wandb-metadata.json",
            "requirements.txt",
            "config.yaml",
            "wandb-summary.json",
        ]
    )


@pytest.mark.flaky
@pytest.mark.xfail(platform.system() == "Windows", reason="flaky test")
@pytest.mark.wandb_core_failure(feature="file_upload")
def test_live_policy_file_upload(live_mock_server, test_settings):
    test_settings.update(
        {
            "start_method": "thread",
            "_live_policy_rate_limit": 2,
            "_live_policy_wait_time": 2,
        },
        source=wandb.sdk.wandb_settings.Source.INIT,
    )

    with wandb.init(settings=test_settings) as run:
        file_path, sent = "saveFile", 0
        # file created, should be uploaded
        with open(file_path, "w") as fp:
            fp.write("a" * 10000)
        run.save(file_path, policy="live")
        # on save file is sent
        sent += os.path.getsize(file_path)
        time.sleep(2.1)
        with open(file_path, "a") as fp:
            fp.write("a" * 10000)
        # 2.1 seconds is longer than set rate limit
        sent += os.path.getsize(file_path)
        # give watchdog time to register the change
        time.sleep(1.0)
        # file updated within modified time, should not be uploaded
        with open(file_path, "a") as fp:
            fp.write("a" * 10000)
        time.sleep(2.0)
        # file updated outside of rate limit should be uploaded
        with open(file_path, "a") as fp:
            fp.write("a" * 10000)
        sent += os.path.getsize(file_path)
        time.sleep(2)

    server_ctx = live_mock_server.get_ctx()
    print(server_ctx["file_bytes"], sent)
    assert "saveFile" in server_ctx["file_bytes"].keys()
    # TODO: bug sometimes it seems that on windows the first file is sent twice
    assert abs(server_ctx["file_bytes"]["saveFile"] - sent) <= 10000
