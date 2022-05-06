"""These test the full stack by launching a real backend server.  You won't get
credit for coverage of the backend logic in these tests.  See test_sender.py for testing
specific backend logic, or wandb_test.py for testing frontend logic.

Be sure to use `test_settings` or an isolated directory
"""
import importlib
import json
import os
import platform
import pytest
import shutil
import subprocess
import time
from unittest import mock

import wandb
from .utils import fixture_open, first_filestream


reloadFn = importlib.reload

# TODO: better debugging, if the backend process fails to start we currently
#  don't get any debug information even in the internal logs.  For now I'm writing
#  logs from all tests that use test_settings to tests/logs/TEST_NAME.  If you're
#  having tests just hang forever, I suggest running test/test_sender to see backend
#  errors until we ensure we propagate the errors up.


def test_resume_allow_success(live_mock_server, test_settings):
    res = live_mock_server.set_ctx({"resume": True})
    print("CTX AFTER UPDATE", res)
    print("GET RIGHT AWAY", live_mock_server.get_ctx())
    run = wandb.init(reinit=True, resume="allow", settings=test_settings)
    run.log({"acc": 10})
    run.finish()
    server_ctx = live_mock_server.get_ctx()
    print("CTX", server_ctx)
    first_stream_hist = first_filestream(server_ctx)["files"]["wandb-history.jsonl"]
    print(first_stream_hist)
    assert first_stream_hist["offset"] == 15
    assert json.loads(first_stream_hist["content"][0])["_step"] == 16
    # TODO: test _runtime offset setting
    # TODO: why no event stream?
    # assert first_stream['files']['wandb-events.jsonl'] == {
    #    'content': ['{"acc": 10, "_step": 15}'], 'offset': 0
    # }


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="File syncing is somewhat busted in windows",
)
def test_parallel_runs(runner, live_mock_server, test_settings, test_name):
    with runner.isolation():
        with open("train.py", "w") as f:
            f.write(fixture_open("train.py").read())
        p1 = subprocess.Popen(["python", "train.py"], env=os.environ)
        p2 = subprocess.Popen(["python", "train.py"], env=os.environ)
        exit_codes = [p.wait() for p in (p1, p2)]
        assert exit_codes == [0, 0]
        num_runs = 0
        # Assert we've stored 2 runs worth of files
        # TODO: not confirming output.log because it is missing sometimes likely due to a BUG
        # TODO: code saving sometimes doesnt work?
        files_sorted = sorted(
            [
                "config.yaml",
                f"code/tests/logs/{test_name}/train.py",
                "requirements.txt",
                "wandb-metadata.json",
                "wandb-summary.json",
            ]
        )
        for run, files in live_mock_server.get_ctx()["storage"].items():
            num_runs += 1
            print("Files from server", files)
            assert (
                sorted(
                    f
                    for f in files
                    if not f.endswith(".patch")
                    and not f.endswith("pt.trace.json")
                    and f != "output.log"
                )
                == files_sorted
            )
        assert num_runs == 2


def test_resume_must_failure(live_mock_server, test_settings):
    with pytest.raises(wandb.Error) as e:
        wandb.init(reinit=True, resume="must", settings=test_settings)
        assert "resume='must' but run" in e.value.message


def test_resume_never_failure(runner, live_mock_server, test_settings):
    with runner.isolation():
        live_mock_server.set_ctx({"resume": True})
        print("CTX", live_mock_server.get_ctx())
        with pytest.raises(wandb.Error) as e:
            wandb.init(reinit=True, resume="never", settings=test_settings)
            assert "resume='never' but run" in e.value.message


def test_resume_auto_success(runner, live_mock_server, test_settings):
    with runner.isolation():
        run = wandb.init(reinit=True, resume=True, settings=test_settings)
        run.finish()
        assert not os.path.exists(test_settings.resume_fname)


def test_resume_auto_failure(live_mock_server, test_settings):
    # env vars have a higher priority than the BASE settings
    # so that if that is set (e.g. by some other test/fixture),
    # test_settings.wandb_dir != run_settings.wandb_dir
    # and this test will fail
    with mock.patch.dict(os.environ, {"WANDB_DIR": test_settings.root_dir}):
        test_settings.update(run_id=None, source=wandb.sdk.wandb_settings.Source.BASE)
        live_mock_server.set_ctx({"resume": True})
        with open(test_settings.resume_fname, "w") as f:
            f.write(json.dumps({"run_id": "resume-me"}))
        run = wandb.init(resume="auto", settings=test_settings)
        assert run.id == "resume-me"
        run.finish(exit_code=3)
        assert os.path.exists(test_settings.resume_fname)


def test_resume_no_metadata(live_mock_server, test_settings):
    # do not write metadata file if we are resuming
    live_mock_server.set_ctx({"resume": True})
    run = wandb.init(resume=True, settings=test_settings)
    run.finish()
    ctx = live_mock_server.get_ctx()
    assert "wandb-metadata.json" not in ctx["storage"][run.id]


def test_include_exclude_config_keys(runner, live_mock_server, test_settings):
    with runner.isolated_filesystem():
        config = {
            "foo": 1,
            "bar": 2,
            "baz": 3,
        }
        run = wandb.init(
            reinit=True,
            resume=True,
            settings=test_settings,
            config=config,
            config_exclude_keys=("bar",),
        )

        assert run.config["foo"] == 1
        assert run.config["baz"] == 3
        assert "bar" not in run.config
        run.finish()

        test_settings._set_run_start_time()  # update timestamp
        run = wandb.init(
            reinit=True,
            resume=True,
            settings=test_settings,
            config=config,
            config_include_keys=("bar",),
        )
        assert run.config["bar"] == 2
        assert "foo" not in run.config
        assert "baz" not in run.config
        run.finish()

        test_settings._set_run_start_time()  # update timestamp
        with pytest.raises(wandb.errors.UsageError):
            wandb.init(
                reinit=True,
                resume=True,
                settings=test_settings,
                config=config,
                config_exclude_keys=("bar",),
                config_include_keys=("bar",),
            )


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


def test_ignore_globs_wandb_files(live_mock_server, test_settings):
    test_settings.update(
        ignore_globs=["requirements.txt"],
        source=wandb.sdk.wandb_settings.Source.INIT,
    )
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
            "config.yaml",
            "wandb-summary.json",
        ]
    )


# TODO(jhr): look into why this timeout needed to be extend for windows
@pytest.mark.timeout(120)
def test_network_fault_graphql(live_mock_server, test_settings):
    # TODO: Initial login fails within 5 seconds so we fail after boot.
    run = wandb.init(settings=test_settings)
    live_mock_server.set_ctx({"fail_graphql_times": 5})
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


def _remove_dir_if_exists(path):
    """Recursively removes directory. Be careful"""
    if os.path.isdir(path):
        shutil.rmtree(path)


def test_dir_on_import(runner, live_mock_server, test_settings):
    """Ensures that `import wandb` does not create a local storage directory"""
    with runner.isolated_filesystem():
        default_path = os.path.join(os.getcwd(), "wandb")
        custom_env_path = os.path.join(os.getcwd(), "env_custom")

        # Test for the base case
        _remove_dir_if_exists(default_path)
        reloadFn(wandb)
        assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
            default_path
        )

        # test for the case that the env variable is set
        with mock.patch.dict(os.environ, {"WANDB_DIR": custom_env_path}):
            _remove_dir_if_exists(default_path)
            reloadFn(wandb)
            assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
                default_path
            )
            assert not os.path.isdir(
                custom_env_path
            ), f"Unexpected directory at {custom_env_path}"


def test_dir_on_init(runner, live_mock_server, test_settings):
    """Ensures that `wandb.init()` creates the proper directory and nothing else"""
    with runner.isolated_filesystem():
        default_path = os.path.join(os.getcwd(), "wandb")

        # Clear env if set
        if "WANDB_DIR" in os.environ:
            del os.environ["WANDB_DIR"]

        # Test for the base case
        reloadFn(wandb)
        _remove_dir_if_exists(default_path)
        run = wandb.init()
        run.finish()
        assert os.path.isdir(default_path), "Expected directory at {}".format(
            default_path
        )


def test_dir_on_init_env(runner, live_mock_server, test_settings):
    """Ensures that `wandb.init()` w/ env variable set creates the proper directory and nothing else"""
    with runner.isolated_filesystem():
        default_path = os.path.join(os.getcwd(), "wandb")
        custom_env_path = os.path.join(os.getcwd(), "env_custom")

        # test for the case that the env variable is set
        with mock.patch.dict(os.environ, {"WANDB_DIR": custom_env_path}):
            if not os.path.isdir(custom_env_path):
                os.makedirs(custom_env_path)
            reloadFn(wandb)
            _remove_dir_if_exists(default_path)
            run = wandb.init()
            run.finish()
            assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
                default_path
            )
            assert os.path.isdir(custom_env_path), "Expected directory at {}".format(
                custom_env_path
            )
            # And for the duplicate-run case
            _remove_dir_if_exists(default_path)
            run = wandb.init()
            run.finish()
            assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
                default_path
            )
            assert os.path.isdir(custom_env_path), "Expected directory at {}".format(
                custom_env_path
            )


def test_dir_on_init_dir(runner, live_mock_server, test_settings):
    """Ensures that `wandb.init(dir=DIR)` creates the proper directory and nothing else"""
    with runner.isolated_filesystem():
        default_path = os.path.join(os.getcwd(), "wandb")
        dir_name = "dir_custom"
        custom_dir_path = os.path.join(os.getcwd(), dir_name)

        # test for the case that the dir is set
        reloadFn(wandb)
        _remove_dir_if_exists(default_path)
        if not os.path.isdir(custom_dir_path):
            os.makedirs(custom_dir_path)
        run = wandb.init(dir="./" + dir_name)
        run.finish()
        assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
            default_path
        )
        assert os.path.isdir(custom_dir_path), "Expected directory at {}".format(
            custom_dir_path
        )
        # And for the duplicate-run case
        _remove_dir_if_exists(default_path)
        run = wandb.init(dir="./" + dir_name)
        run.finish()
        assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
            default_path
        )
        assert os.path.isdir(custom_dir_path), "Expected directory at {}".format(
            custom_dir_path
        )


def test_version_upgraded(live_mock_server, capsys):
    with mock.patch("wandb.__version__", "0.10.2"):
        run = wandb.init(settings=dict(console="off"))
        captured = capsys.readouterr()
        assert "is available!  To upgrade, please run:" in captured.err
        run.finish()


def test_version_yanked(live_mock_server, capsys):
    with mock.patch("wandb.__version__", "0.10.0"):
        run = wandb.init(settings=dict(console="off"))
        captured = capsys.readouterr()
        assert "WARNING wandb version 0.10.0 has been recalled" in captured.err
        run.finish()


def test_version_retired(live_mock_server, capsys):
    with mock.patch("wandb.__version__", "0.9.99"):
        run = wandb.init(settings=dict(console="off"))
        captured = capsys.readouterr()
        assert "ERROR wandb version 0.9.99 has been retired" in captured.err
        run.finish()


def test_end_to_end_preempting(live_mock_server):
    run = wandb.init(settings=dict(console="off"))
    run.mark_preempting()

    # poll for message arrival
    ok = False
    for _ in range(3):
        ctx = live_mock_server.get_ctx()
        if "file_stream" in ctx:
            ok = any(
                ["preempting" in request_dict for request_dict in ctx["file_stream"]]
            )
            if ok:
                break
        time.sleep(1)
    assert ok
    run.finish()


def test_end_to_end_preempting_via_module_func(live_mock_server):
    run = wandb.init(settings=dict(console="off"))
    run.log({"a": 1})
    run.mark_preempting()

    # poll for message arrival
    ok = False
    for _ in range(3):
        ctx = live_mock_server.get_ctx()
        if "file_stream" in ctx:
            ok = any(
                ["preempting" in request_dict for request_dict in ctx["file_stream"]]
            )
            if ok:
                break
        time.sleep(1)
    assert ok
    run.finish()


@pytest.mark.flaky
@pytest.mark.xfail(platform.system() == "Windows", reason="flaky test")
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
        # test flakes as I/O on CircleCI may be slow at times
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
