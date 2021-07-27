from __future__ import print_function

import os
import pytest
import six
from six.moves import queue
import threading
import time
import shutil
import sys

import wandb
from wandb.util import mkdir_exists_ok

from .utils import first_filestream


def test_send_status_request_stopped(mock_server, backend_interface):
    mock_server.ctx["stopped"] = True

    with backend_interface() as interface:
        status_resp = interface.communicate_stop_status()
        assert status_resp is not None
        assert status_resp.run_should_stop


def test_parallel_requests(mock_server, backend_interface):
    mock_server.ctx["stopped"] = True
    work_queue = queue.Queue()

    with backend_interface() as interface:

        def send_sync_request(i):
            work_queue.get()
            if i % 3 == 0:
                status_resp = interface.communicate_stop_status()
                assert status_resp is not None
                assert status_resp.run_should_stop
            elif i % 3 == 2:
                summary_resp = interface.communicate_summary()
                assert summary_resp is not None
                assert hasattr(summary_resp, "item")
            work_queue.task_done()

        for i in range(10):
            work_queue.put(None)
            t = threading.Thread(target=send_sync_request, args=(i,))
            t.daemon = True
            t.start()

        work_queue.join()


def test_send_status_request_network(mock_server, backend_interface):
    mock_server.ctx["rate_limited_times"] = 3

    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "live")]})

        status_resp = interface.communicate_network_status()
        assert status_resp is not None
        assert len(status_resp.network_responses) > 0
        assert status_resp.network_responses[0].http_status_code == 429


def test_resume_success(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.resume = "allow"
    mock_server.ctx["resume"] = True
    with backend_interface(initial_run=False) as interface:
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error") is False
        assert run_result.run.starting_step == 16


def test_resume_error_never(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.resume = "never"
    mock_server.ctx["resume"] = True
    with backend_interface(initial_run=False) as interface:
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error")
        assert (
            run_result.error.message
            == "resume='never' but run (%s) exists" % mocked_run.id
        )


def test_resume_error_must(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.resume = "must"
    mock_server.ctx["resume"] = False
    with backend_interface(initial_run=False) as interface:
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error")
        assert (
            run_result.error.message
            == "resume='must' but run (%s) doesn't exist" % mocked_run.id
        )


def test_save_live_existing_file(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")
        interface.publish_files({"files": [("test.txt", "live")]})

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1
    assert any(
        [
            "test.txt" in request_dict.get("uploaded", [])
            for request_dict in mock_server.ctx["file_stream"]
        ]
    )


def test_save_live_write_after_policy(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "live")]})
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_preempting_sent_to_server(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_preempting()
    assert any(
        [
            "preempting" in request_dict
            for request_dict in mock_server.ctx["file_stream"]
        ]
    )


def test_save_live_multi_write(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "live")]})
        test_file = os.path.join(mocked_run.dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        with open(test_file, "w") as f:
            f.write("TEST TEST TEST TEST")

    assert len(mock_server.ctx["storage?file=test.txt"]) == 2


def test_save_live_glob_multi_write(mocked_run, mock_server, mocker, backend_interface):
    def mock_min_size(self, size):
        return 1

    mocker.patch("wandb.filesync.dir_watcher.PolicyLive.RATE_LIMIT_SECONDS", 1)
    mocker.patch(
        "wandb.filesync.dir_watcher.PolicyLive.min_wait_for_size", mock_min_size
    )

    with backend_interface() as interface:
        interface.publish_files({"files": [("checkpoints/*", "live")]})
        mkdir_exists_ok(os.path.join(mocked_run.dir, "checkpoints"))
        test_file_1 = os.path.join(mocked_run.dir, "checkpoints", "test_1.txt")
        test_file_2 = os.path.join(mocked_run.dir, "checkpoints", "test_2.txt")
        # To debug this test adds some prints to the dir_watcher.py _on_file_* handlers
        print("Wrote file 1")
        with open(test_file_1, "w") as f:
            f.write("TEST TEST")
        time.sleep(2)
        print("Wrote file 1 2nd time")
        with open(test_file_1, "w") as f:
            f.write("TEST TEST TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        print("Wrote file 2")
        with open(test_file_2, "w") as f:
            f.write("TEST TEST TEST TEST")
        print("Wrote file 1 3rd time")
        with open(test_file_1, "w") as f:
            f.write("TEST TEST TEST TEST TEST TEST")
        print("Stopping backend")

    print("Backend stopped")
    print(
        "CTX:", [(k, v) for k, v in mock_server.ctx.items() if k.startswith("storage")]
    )

    assert len(mock_server.ctx["storage?file=checkpoints/test_1.txt"]) == 3
    assert len(mock_server.ctx["storage?file=checkpoints/test_2.txt"]) == 1


def test_save_rename_file(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "live")]})
        test_file = os.path.join(mocked_run.dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        shutil.copy(test_file, test_file.replace("test.txt", "test-copy.txt"))

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1
    assert len(mock_server.ctx["storage?file=test-copy.txt"]) == 1


def test_save_end_write_after_policy(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "end")]})
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_end_existing_file(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")
        interface.publish_files({"files": [("test.txt", "end")]})

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_end_multi_write(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "end")]})
        test_file = os.path.join(mocked_run.dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        with open(test_file, "w") as f:
            f.write("TEST TEST TEST TEST")

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_write_after_policy(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "now")]})
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_existing_file(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")
        interface.publish_files({"files": [("test.txt", "now")]})

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_multi_write(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "now")]})
        test_file = os.path.join(mocked_run.dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        with open(test_file, "w") as f:
            f.write("TEST TEST TEST TEST")

    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_glob_multi_write(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("checkpoints/*", "now")]})
        mkdir_exists_ok(os.path.join(mocked_run.dir, "checkpoints"))
        test_file_1 = os.path.join(mocked_run.dir, "checkpoints", "test_1.txt")
        test_file_2 = os.path.join(mocked_run.dir, "checkpoints", "test_2.txt")
        print("Wrote file 1")
        with open(test_file_1, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        print("Wrote file 2")
        with open(test_file_2, "w") as f:
            f.write("TEST TEST TEST TEST")
        time.sleep(1.5)
        print("Stopping backend")

    print("Backend stopped")
    print(
        "CTX", [(k, v) for k, v in mock_server.ctx.items() if k.startswith("storage")]
    )
    assert len(mock_server.ctx["storage?file=checkpoints/test_1.txt"]) == 1
    assert len(mock_server.ctx["storage?file=checkpoints/test_2.txt"]) == 1


def test_save_now_relative_path(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        interface.publish_files({"files": [("foo/test.txt", "now")]})
        test_file = os.path.join(mocked_run.dir, "foo", "test.txt")
        mkdir_exists_ok(os.path.dirname(test_file))
        with open(test_file, "w") as f:
            f.write("TEST TEST")

    print("DAMN DUDE", mock_server.ctx)
    assert len(mock_server.ctx["storage?file=foo/test.txt"]) == 1


def test_save_now_twice(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        file_path = os.path.join("foo", "test.txt")
        interface.publish_files({"files": [(file_path, "now")]})
        test_file = os.path.join(mocked_run.dir, file_path)
        mkdir_exists_ok(os.path.dirname(test_file))
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        time.sleep(1.5)
        with open(test_file, "w") as f:
            f.write("TEST TEST TEST TEST")
        interface.publish_files({"files": [(file_path, "now")]})

    print("DAMN DUDE", mock_server.ctx)
    assert len(mock_server.ctx["storage?file=foo/test.txt"]) == 2


def test_output(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        for i in range(100):
            interface.publish_output("stdout", "\rSome recurring line")
        interface.publish_output("stdout", "\rFinal line baby\n")

    print("DUDE!", mock_server.ctx)
    stream = first_filestream(mock_server.ctx)
    assert "Final line baby" in stream["files"]["output.log"]["content"][0]


def test_sync_spell_run(mocked_run, mock_server, backend_interface, parse_ctx):
    try:
        os.environ["SPELL_RUN_URL"] = "https://spell.run/foo"
        with backend_interface() as interface:
            pass
        print("CTX", mock_server.ctx)
        ctx = parse_ctx(mock_server.ctx)
        assert ctx.config["_wandb"]["value"]["spell_url"] == "https://spell.run/foo"
        # Check that we pinged spells API
        assert mock_server.ctx["spell_data"] == {
            "access_token": None,
            "url": "{}/mock_server_entity/test/runs/{}".format(
                mocked_run._settings.base_url, mocked_run.id
            ),
        }
    finally:
        del os.environ["SPELL_RUN_URL"]


def test_upgrade_upgraded(
    mocked_run, mock_server, backend_interface, restore_version,
):
    wandb.__version__ = "0.0.6"
    wandb.__hack_pypi_latest_version__ = "0.0.8"
    with backend_interface(initial_run=False) as interface:
        ret = interface.communicate_check_version()
        assert ret
        assert (
            ret.upgrade_message
            == "wandb version 0.0.8 is available!  To upgrade, please run:\n $ pip install wandb --upgrade"
        )
        assert not ret.delete_message
        assert not ret.yank_message

        # We need a run to cleanly shutdown backend
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error") is False


def test_upgrade_yanked(
    mocked_run, mock_server, backend_interface, restore_version,
):
    wandb.__version__ = "0.0.2"
    wandb.__hack_pypi_latest_version__ = "0.0.8"
    with backend_interface(initial_run=False) as interface:
        ret = interface.communicate_check_version()
        assert ret
        assert (
            ret.upgrade_message
            == "wandb version 0.0.8 is available!  To upgrade, please run:\n $ pip install wandb --upgrade"
        )
        assert not ret.delete_message
        assert (
            ret.yank_message
            == "wandb version 0.0.2 has been recalled!  Please upgrade."
        )

        # We need a run to cleanly shutdown backend
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error") is False


def test_upgrade_yanked_message(
    mocked_run, mock_server, backend_interface, restore_version,
):
    wandb.__version__ = "0.0.3"
    wandb.__hack_pypi_latest_version__ = "0.0.8"
    with backend_interface(initial_run=False) as interface:
        ret = interface.communicate_check_version()
        assert ret
        assert (
            ret.upgrade_message
            == "wandb version 0.0.8 is available!  To upgrade, please run:\n $ pip install wandb --upgrade"
        )
        assert not ret.delete_message
        assert (
            ret.yank_message
            == "wandb version 0.0.3 has been recalled!  (just cuz)  Please upgrade."
        )

        # We need a run to cleanly shutdown backend
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error") is False


def test_upgrade_removed(
    mocked_run, mock_server, backend_interface, restore_version,
):
    wandb.__version__ = "0.0.4"
    wandb.__hack_pypi_latest_version__ = "0.0.8"
    with backend_interface(initial_run=False) as interface:
        ret = interface.communicate_check_version()
        assert ret
        assert (
            ret.upgrade_message
            == "wandb version 0.0.8 is available!  To upgrade, please run:\n $ pip install wandb --upgrade"
        )
        assert (
            ret.delete_message
            == "wandb version 0.0.4 has been retired!  Please upgrade."
        )
        assert not ret.yank_message

        # We need a run to cleanly shutdown backend
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error") is False


# TODO: test other sender methods
