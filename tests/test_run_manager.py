import datetime
import io
import os
import time
import json
import pytest
import threading

import wandb.run_manager
from wandb.apis import internal
import wandb
from wandb import wandb_socket
from wandb.wandb_run import Run, RESUME_FNAME
from wandb.run_manager import FileEventHandlerThrottledOverwriteMinWait, FileEventHandlerOverwriteDeferred, FileEventHandlerOverwrite, FileEventHandlerOverwriteOnce
from click.testing import CliRunner


def test_check_update_available_equal(request_mocker, capsys, query_viewer):
    "Test update availability in different cases."
    test_cases = [
        ('0.8.10', '0.8.10', False),
        ('0.8.9', '0.8.10', True),
        ('0.8.11', '0.8.10', False),
        ('1.0.0', '2.0.0', True),
        ('0.4.5', '0.4.5a5', False),
        ('0.4.5', '0.4.3b2', False),
        ('0.4.5', '0.4.6b2', True),
        ('0.4.5.alpha', '0.4.4', False),
        ('0.4.5.alpha', '0.4.5', True),
        ('0.4.5.alpha', '0.4.6', True)
    ]

    for current, latest, is_expected in test_cases:
        with CliRunner().isolated_filesystem():
            query_viewer(request_mocker)
            is_avail = _is_update_avail(
                request_mocker, capsys, current, latest)
            assert is_avail == is_expected, "expected {} compared to {} to yield update availability of {}".format(
                current, latest, is_expected)


def _is_update_avail(request_mocker, capsys, current, latest):
    "Set up the run manager and detect if the upgrade message is printed."
    api = internal.Api(
        load_settings=False,
        retry_timedelta=datetime.timedelta(0, 0, 50))
    api.set_current_run_id(123)
    run = Run()
    run_manager = wandb.run_manager.RunManager(run)

    # Without this mocking, during other tests, the _check_update_available
    # function will throw a "mock not found" error, then silently fail without
    # output (just like it would in a normal network failure).
    response = b'{ "info": { "version": "%s" } }' % bytearray(latest, 'utf-8')
    request_mocker.register_uri('GET', 'https://pypi.org/pypi/wandb/json',
                                content=response, status_code=200)
    run_manager._check_update_available(current)

    captured_out, captured_err = capsys.readouterr()
    print(captured_out, captured_err)
    return "To upgrade, please run:" in captured_err


def test_throttle_file_poller(mocker, run_manager):
    emitter = run_manager.emitter
    assert emitter.timeout == 1
    for i in range(100):
        with open(os.path.join(wandb.run.dir, "file_%i.txt" % i), "w") as f:
            f.write(str(i))
    run_manager.test_shutdown()
    assert emitter.timeout == 2


def test_pip_freeze(mocker, run_manager):
    run_manager._block_file_observer()
    run_manager.init_run()
    # TODO(adrian): I've seen issues with this test when the W&B version
    # installed for the current python differs from the one (eg. from git)
    # that is running this test. Easy fix is to do "pip install -e ."
    reqs = open(os.path.join(wandb.run.dir, "requirements.txt")).read()
    print([r for r in reqs.split("\n") if "wandb" in r])
    wbv = "wandb==%s" % wandb.__version__
    assert wbv in reqs


def test_custom_file_policy(mocker, run_manager):
    run_manager._block_file_observer()
    run_manager.init_run()
    for i in range(5):
        with open(os.path.join(wandb.run.dir, "ckpt_%i.txt" % i), "w") as f:
            f.write(str(i))
    wandb.save("ckpt*")
    with open(os.path.join(wandb.run.dir, "foo.bar"), "w") as f:
        f.write("bar")

    run_manager.test_shutdown()
    assert isinstance(
        run_manager._file_event_handlers["ckpt_0.txt"], FileEventHandlerThrottledOverwriteMinWait)
    assert isinstance(
        run_manager._file_event_handlers["foo.bar"], FileEventHandlerOverwriteDeferred)
    assert isinstance(
        run_manager._file_event_handlers["wandb-metadata.json"], FileEventHandlerOverwriteOnce)
    assert isinstance(
        run_manager._file_event_handlers["requirements.txt"], FileEventHandlerOverwrite)


def test_custom_file_policy_symlink(mocker, run_manager):
    mod = mocker.MagicMock()
    mocker.patch(
        'wandb.run_manager.FileEventHandlerThrottledOverwriteMinWait.on_modified', mod)
    with open("ckpt_0.txt", "w") as f:
        f.write("joy")
    with open("ckpt_1.txt", "w") as f:
        f.write("joy" * 100)
    wandb.save("ckpt_0.txt")
    with open("ckpt_0.txt", "w") as f:
        f.write("joy" * 100)
    wandb.save("ckpt_1.txt")
    run_manager.test_shutdown()
    assert isinstance(
        run_manager._file_event_handlers["ckpt_0.txt"], FileEventHandlerThrottledOverwriteMinWait)
    assert mod.called


def test_remove_auto_resume(mocker, run_manager):
    resume_path = os.path.join(wandb.wandb_dir(), RESUME_FNAME)
    with open(resume_path, "w") as f:
        f.write("{}")
    run_manager.test_shutdown()
    assert not os.path.exists(resume_path)


def test_sync_etc_multiple_messages(mocker, run_manager):
    mocked_policy = mocker.MagicMock()
    run_manager.update_user_file_policy = mocked_policy
    payload = json.dumps(
        {"save_policy": {"glob": "*.foo", "policy": "end"}}).encode("utf8")
    wandb.run.socket.connection.sendall(payload + b"\0" + payload + b"\0")
    run_manager.test_shutdown()
    assert len(mocked_policy.mock_calls) == 2


def test_init_run_network_down(mocker, caplog):
    with CliRunner().isolated_filesystem():
        mocker.patch("wandb.apis.internal.Api.HTTP_TIMEOUT", 0.5)
        api = internal.Api(
            load_settings=False,
            retry_timedelta=datetime.timedelta(0, 0, 50))
        api.set_current_run_id(123)
        run = Run()
        mocker.patch("wandb.run_manager.RunManager._upsert_run",
                     lambda *args: time.sleep(0.6))
        rm = wandb.run_manager.RunManager(run)
        step = rm.init_run()
        assert step == 0
        assert "Failed to connect" in caplog.text
