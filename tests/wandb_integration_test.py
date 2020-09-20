"""These test the full stack by launching a real backend server.  You won't get
credit for coverage of the backend logic in these tests.  See test_sender.py for testing
specific backend logic, or wandb_test.py for testing frontend logic.

Be sure to use `test_settings` or an isolated directory
"""
import wandb
import pytest
import json
import platform
import subprocess
import os
from .utils import fixture_open

# TODO: better debugging, if the backend process fails to start we currently
# don't get any debug information even in the internal logs.  For now I'm writing
# logs from all tests that use test_settings to tests/logs/TEST_NAME.  If you're
# having tests just hang forever, I suggest running test/test_sender to see backend
# errors until we ensure we propogate the errors up.


def test_resume_allow_success(live_mock_server, test_settings):
    res = live_mock_server.set_ctx({"resume": True})
    print("CTX AFTER UPDATE", res)
    print("GET RIGHT AWAY", live_mock_server.get_ctx())
    wandb.init(reinit=True, resume="allow", settings=test_settings)
    wandb.log({"acc": 10})
    wandb.join()
    server_ctx = live_mock_server.get_ctx()
    print("CTX", server_ctx)
    first_stream_hist = server_ctx["file_stream"][0]["files"]["wandb-history.jsonl"]
    print(first_stream_hist)
    assert first_stream_hist["offset"] == 15
    assert json.loads(first_stream_hist["content"][0])["_step"] == 16
    # TODO: test _runtime offset setting
    # TODO: why no event stream?
    # assert first_stream['files']['wandb-events.jsonl'] == {
    #    'content': ['{"acc": 10, "_step": 15}'], 'offset': 0
    # }


@pytest.mark.skipif(platform.system() == "Windows", reason="File syncing is somewhat busted in windows")
# TODO: Sometimes wandb-summary.json didn't exists, other times requirements.txt in windows
def test_parallel_runs(live_mock_server, test_settings):
    with open("train.py", "w") as f:
        f.write(fixture_open("train.py").read())
    p1 = subprocess.Popen(["python", "train.py"], env=os.environ)
    p2 = subprocess.Popen(["python", "train.py"], env=os.environ)
    exit_codes = [p.wait() for p in (p1, p2)]
    assert exit_codes == [0,0]
    num_runs = 0
    # Assert we've stored 2 runs worth of files
    # TODO: not confirming output.log because it is missing sometimes likely due to a BUG
    files_sorted = sorted([
        'wandb-metadata.json', 'code/tests/logs/test_parallel_runs/train.py',
        'requirements.txt', 'config.yaml',
        'wandb-summary.json'])
    for run,files in live_mock_server.get_ctx()["storage"].items():
        num_runs += 1
        print("Files from server", files)
        assert sorted([f for f in files if not f.endswith(".patch") and f != "output.log"]) == files_sorted
    assert num_runs == 2


def test_resume_must_failure(live_mock_server, test_settings):
    with pytest.raises(wandb.Error) as e:
        wandb.init(reinit=True, resume="must", settings=test_settings)
    assert "resume='must' but run" in e.value.message


def test_resume_never_failure(live_mock_server, test_settings):
    # TODO: this test passes independently but fails in the suite
    live_mock_server.set_ctx({"resume": True})
    print("CTX", live_mock_server.get_ctx())
    with pytest.raises(wandb.Error) as e:
        wandb.init(reinit=True, resume="never", settings=test_settings)
    assert "resume='never' but run" in e.value.message


def test_resume_auto_success(live_mock_server, test_settings):
    run = wandb.init(reinit=True, resume=True, settings=test_settings)
    run.join()
    assert not os.path.exists(test_settings.resume_fname)


def test_resume_auto_failure(live_mock_server, test_settings):
    test_settings.run_id = None
    with open(test_settings.resume_fname, "w") as f:
        f.write(json.dumps({"run_id": "resumeme"}))
    run = wandb.init(reinit=True, resume=True, settings=test_settings)
    assert run.id == "resumeme"
    run.join(exit_code=3)
    assert os.path.exists(test_settings.resume_fname)


def test_include_exclude_config_keys(live_mock_server, test_settings):
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
    run.join()

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
    run.join()

    with pytest.raises(wandb.errors.error.UsageError):
        run = wandb.init(
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
    run.join()
    ctx = live_mock_server.get_ctx()
    print(ctx)
    assert [f for f in sorted(ctx["storage"][run.id]) if not f.endswith(".patch") and not f.endswith(".py")] == sorted(
        ['wandb-metadata.json', 'requirements.txt', 'config.yaml', 'wandb-summary.json',])


def test_network_fault_graphql(live_mock_server, test_settings):
    # TODO: Initial login fails within 5 seconds so we fail after boot.
    run = wandb.init(settings=test_settings)
    live_mock_server.set_ctx({"fail_graphql_times": 5})
    run.join()
    ctx = live_mock_server.get_ctx()
    print(ctx)
    assert [f for f in sorted(ctx["storage"][run.id]) if not f.endswith(".patch") and not f.endswith(".py")] == sorted(
        ['wandb-metadata.json', 'requirements.txt', 'config.yaml', 'wandb-summary.json',])
