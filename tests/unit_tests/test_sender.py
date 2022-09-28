import os
import shutil
import time
import unittest.mock

import pytest
import wandb
from wandb.util import mkdir_exists_ok


def test_save_live_existing_file(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    file_name = "wandb.rules"

    with relay_server() as relay, backend_interface(run) as interface:
        with open(os.path.join(run.dir, file_name), "w") as f:
            f.write("BOOM BOOM")
        interface.publish_files({"files": [(file_name, "live")]})

    uploaded_files = relay.context.get_run_uploaded_files(run.id)

    assert file_name in uploaded_files
    assert uploaded_files.count(file_name) == 1


def test_save_live_write_after_policy(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    file_name = "wandb.rules"

    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [(file_name, "live")]})
        with open(os.path.join(run.dir, file_name), "w") as f:
            f.write("TEST TEST")

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count(file_name) == 1


def test_preempting_sent_to_server(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_preempting()

    assert relay.context.entries[run.id].get("preempting") is not None


def test_save_live_multi_write(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    file_name = "wandb.rules"

    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [(file_name, "live")]})
        test_file = os.path.join(run.dir, file_name)
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        with open(test_file, "w") as f:
            f.write("TEST TEST TEST TEST")

    uploaded_files = relay.context.get_run_uploaded_files(run.id)

    assert file_name in uploaded_files
    assert uploaded_files.count(file_name) == 2


@pytest.mark.xfail(reason="TODO: fix this test")
def test_save_live_glob_multi_write(
    relay_server, user, mock_run, backend_interface, mocker
):
    run = mock_run(use_magic_mock=True)

    mocker.patch("wandb.filesync.dir_watcher.PolicyLive.RATE_LIMIT_SECONDS", 1)
    mocker.patch(
        "wandb.filesync.dir_watcher.PolicyLive.min_wait_for_size", lambda self, size: 1
    )

    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [("checkpoints/*", "live")]})
        mkdir_exists_ok(os.path.join(run.dir, "checkpoints"))
        test_file_1 = os.path.join(run.dir, "checkpoints", "test_1.txt")
        test_file_2 = os.path.join(run.dir, "checkpoints", "test_2.txt")
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

    uploaded_files = relay.context.get_run_uploaded_files(run.id)

    assert uploaded_files.count("checkpoints/test_1.txt") == 3
    assert uploaded_files.count("checkpoints/test_2.txt") == 1


def test_save_rename_file(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [("test.txt", "live")]})
        test_file = os.path.join(run.dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        shutil.copy(test_file, test_file.replace("test.txt", "test-copy.txt"))

    uploaded_files = relay.context.get_run_uploaded_files(run.id)

    assert uploaded_files.count("test.txt") == 1
    assert uploaded_files.count("test-copy.txt") == 1


def test_save_end_write_after_policy(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [("test.txt", "end")]})
        with open(os.path.join(run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("test.txt") == 1


def test_save_end_existing_file(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        with open(os.path.join(run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")
        interface.publish_files({"files": [("test.txt", "end")]})

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("test.txt") == 1


def test_save_end_multi_write(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [("test.txt", "end")]})
        test_file = os.path.join(run.dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        with open(test_file, "w") as f:
            f.write("TEST TEST TEST TEST")

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("test.txt") == 1


@pytest.mark.xfail(reason="This test is flakey")
def test_save_now_write_after_policy(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [("test.txt", "now")]})
        with open(os.path.join(run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")
        time.sleep(1.5)

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("test.txt") == 1


def test_save_now_existing_file(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        with open(os.path.join(run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")
        interface.publish_files({"files": [("test.txt", "now")]})

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("test.txt") == 1


@pytest.mark.xfail(reason="This test is flakey")
def test_save_now_multi_write(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [("test.txt", "now")]})
        test_file = os.path.join(run.dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        # File system polling happens every second
        time.sleep(1.5)
        with open(test_file, "w") as f:
            f.write("TEST TEST TEST TEST")

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("test.txt") == 1


def test_save_glob_multi_write(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [("checkpoints/*", "now")]})
        mkdir_exists_ok(os.path.join(run.dir, "checkpoints"))
        test_file_1 = os.path.join(run.dir, "checkpoints", "test_1.txt")
        test_file_2 = os.path.join(run.dir, "checkpoints", "test_2.txt")
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

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("checkpoints/test_1.txt") == 1
    assert uploaded_files.count("checkpoints/test_2.txt") == 1


@pytest.mark.xfail(reason="This test is flakey")
def test_save_now_relative_path(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        interface.publish_files({"files": [("foo/test.txt", "now")]})
        test_file = os.path.join(run.dir, "foo", "test.txt")
        mkdir_exists_ok(os.path.dirname(test_file))
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        time.sleep(1.5)

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("foo/test.txt") == 1


@pytest.mark.xfail(reason="TODO: This test is flakey")
def test_save_now_twice(relay_server, user, mock_run, backend_interface):
    run = mock_run(use_magic_mock=True)
    with relay_server() as relay, backend_interface(run) as interface:
        file_path = os.path.join("foo", "test.txt")
        interface.publish_files({"files": [(file_path, "now")]})
        test_file = os.path.join(run.dir, file_path)
        mkdir_exists_ok(os.path.dirname(test_file))
        with open(test_file, "w") as f:
            f.write("TEST TEST")
        time.sleep(1.5)
        with open(test_file, "w") as f:
            f.write("TEST TEST TEST TEST")
        interface.publish_files({"files": [(file_path, "now")]})
        time.sleep(1.5)

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert uploaded_files.count("foo/test.txt") == 2


def test_upgrade_upgraded(
    mock_run,
    backend_interface,
    user,
):
    run = mock_run(use_magic_mock=True)
    with backend_interface(run, initial_run=False) as interface:
        with unittest.mock.patch.object(
            wandb,
            "__version__",
            "0.0.6",
        ), unittest.mock.patch.object(
            wandb.sdk.internal.sender.update,
            "_find_available",
            lambda current_version: ("0.0.8", False, False, False, ""),
        ):
            ret = interface.communicate_check_version()
            assert ret
            assert (
                ret.upgrade_message
                == "wandb version 0.0.8 is available!  To upgrade, please run:\n $ pip install wandb --upgrade"
            )
            assert not ret.delete_message
            assert not ret.yank_message

        # We need a run to cleanly shutdown backend
        run_result = interface.communicate_run(run)
        assert run_result.HasField("error") is False


def test_upgrade_yanked(
    mock_run,
    backend_interface,
    user,
):
    run = mock_run(use_magic_mock=True)
    with backend_interface(run, initial_run=False) as interface:
        with unittest.mock.patch.object(
            wandb,
            "__version__",
            "0.0.2",
        ), unittest.mock.patch.object(
            wandb.sdk.internal.sender.update,
            "_find_available",
            lambda current_version: ("0.0.8", False, False, True, ""),
        ):

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
        run_result = interface.communicate_run(run)
        assert run_result.HasField("error") is False


def test_upgrade_yanked_message(
    mock_run,
    backend_interface,
    user,
):
    run = mock_run(use_magic_mock=True)
    with backend_interface(run, initial_run=False) as interface:
        with unittest.mock.patch.object(
            wandb,
            "__version__",
            "0.0.3",
        ), unittest.mock.patch.object(
            wandb.sdk.internal.sender.update,
            "_find_available",
            lambda current_version: ("0.0.8", False, False, True, "just cuz"),
        ):

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
        run_result = interface.communicate_run(run)
        assert run_result.HasField("error") is False


def test_upgrade_removed(
    mock_run,
    backend_interface,
    user,
):
    run = mock_run(use_magic_mock=True)
    with backend_interface(run, initial_run=False) as interface:
        with unittest.mock.patch.object(
            wandb,
            "__version__",
            "0.0.4",
        ), unittest.mock.patch.object(
            wandb.sdk.internal.sender.update,
            "_find_available",
            lambda current_version: ("0.0.8", False, True, False, ""),
        ):
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
        run_result = interface.communicate_run(run)
        assert run_result.HasField("error") is False
