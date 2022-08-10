import os
import platform
import queue
import sys
import tempfile
import threading
import time
from unittest import mock

import pytest
import wandb


@pytest.fixture
def mock_tty(monkeypatch):
    class WriteThread(threading.Thread):
        def __init__(self, fname):
            threading.Thread.__init__(self)
            self._fname = fname
            self._q = queue.Queue()

        def run(self):
            with open(self._fname, "w") as fp:
                while True:
                    data = self._q.get()
                    if data == "_DONE_":
                        break
                    fp.write(data)
                    fp.flush()

        def add(self, input_str):
            self._q.put(input_str)

        def stop(self):
            self.add("_DONE_")

    with tempfile.TemporaryDirectory() as tmpdir:
        fds = dict()

        def setup_fn(input_str):
            fname = os.path.join(tmpdir, "file.txt")
            if platform.system() != "Windows":
                os.mkfifo(fname, 0o600)
                writer = WriteThread(fname)
                writer.start()
                writer.add(input_str)
                fds["writer"] = writer
                monkeypatch.setattr("termios.tcflush", lambda x, y: None)
            else:
                # windows doesn't support named pipes, just write it
                # TODO: emulate msvcrt to support input on windows
                with open(fname, "w") as fp:
                    fp.write(input_str)
            fds["stdin"] = open(fname)
            monkeypatch.setattr("sys.stdin", fds["stdin"])
            sys.stdin.isatty = lambda: True
            sys.stdout.isatty = lambda: True

        yield setup_fn

        writer = fds.get("writer")
        if writer:
            writer.stop()
            writer.join()
        stdin = fds.get("stdin")
        if stdin:
            stdin.close()

    del sys.stdin.isatty
    del sys.stdout.isatty


def test_login_timeout(mock_tty):
    mock_tty("junk\nmore\n")
    start_time = time.time()
    ret = wandb.login(timeout=4)
    elapsed = time.time() - start_time
    assert 2 < elapsed < 15
    assert ret is False
    assert wandb.api.api_key is None
    assert wandb.setup().settings.mode == "disabled"


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="mock_tty doesnt support windows input yet",
)
def test_login_timeout_choose(mock_tty):
    mock_tty("3\n")
    start_time = time.time()
    ret = wandb.login(timeout=8)
    elapsed = time.time() - start_time
    assert elapsed < 15
    assert ret is False
    assert wandb.api.api_key is None
    assert wandb.setup().settings.mode == "offline"


def test_login_timeout_env_blank(mock_tty):
    mock_tty("\n\n\n")
    with mock.patch.dict(os.environ, {"WANDB_LOGIN_TIMEOUT": "4"}):
        start_time = time.time()
        ret = wandb.login()
        elapsed = time.time() - start_time
        assert elapsed < 15
        assert ret is False
        assert wandb.api.api_key is None
        assert wandb.setup().settings.mode == "disabled"


def test_login_timeout_env_invalid(mock_tty):
    mock_tty("")
    with mock.patch.dict(os.environ, {"WANDB_LOGIN_TIMEOUT": "junk"}):
        with pytest.raises(ValueError):
            wandb.login()


def test_relogin_timeout(dummy_api_key):
    logged_in = wandb.login(relogin=True, key=dummy_api_key)
    assert logged_in is True
    logged_in = wandb.login()
    assert logged_in is True


def test_login_key(capsys):
    wandb.login(key="A" * 40)
    # TODO: this was a bug when tests were leaking out to the global config
    # wandb.api.set_setting("base_url", "http://localhost:8080")
    out, err = capsys.readouterr()
    print(out)
    print(err)
    assert "Appending key" in err
    #  WTF is happening?
    assert wandb.api.api_key == "A" * 40


def test_login(test_settings):
    settings = test_settings(dict(mode="disabled"))
    wandb.setup(settings=settings)
    wandb.login()
    wandb.finish()


def test_login_anonymous():
    with mock.patch.dict("os.environ", WANDB_API_KEY="ANONYMOOSE" * 4):
        wandb.login(anonymous="must")
        assert wandb.api.api_key == "ANONYMOOSE" * 4


def test_login_sets_api_base_url(local_settings):
    with mock.patch.dict("os.environ", WANDB_API_KEY="ANONYMOOSE" * 4):
        base_url = "https://api.test.host.ai"
        wandb.login(anonymous="must", host=base_url)
        api = wandb.Api()
        assert api.settings["base_url"] == base_url
        base_url = "https://api.wandb.ai"
        wandb.login(anonymous="must", host=base_url)
        api = wandb.Api()
        assert api.settings["base_url"] == base_url


@pytest.mark.skip(reason="We dont validate keys in `wandb.login()` right now")
def test_login_invalid_key():
    with mock.patch.dict("os.environ", WANDB_API_KEY="B" * 40):
        wandb.ensure_configured()
        with pytest.raises(wandb.UsageError):
            wandb.login()
