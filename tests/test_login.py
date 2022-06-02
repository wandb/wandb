"""
login tests.
"""

import os
import platform
import pytest
import time

import wandb
from wandb.errors import UsageError


@pytest.fixture
def reset_login_timeout():
    yield
    del os.environ["WANDB_LOGIN_TIMEOUT"]


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


def test_login_timeout_env_blank(mock_tty, reset_login_timeout):
    mock_tty("\n\n\n")
    os.environ["WANDB_LOGIN_TIMEOUT"] = "4"
    start_time = time.time()
    ret = wandb.login()
    elapsed = time.time() - start_time
    assert elapsed < 15
    assert ret is False
    assert wandb.api.api_key is None
    assert wandb.setup().settings.mode == "disabled"


def test_login_timeout_env_invalid(mock_tty, reset_login_timeout):
    mock_tty("")
    os.environ["WANDB_LOGIN_TIMEOUT"] = "junk"

    with pytest.raises(ValueError):
        wandb.login()


def test_relogin_timeout(test_settings, dummy_api_key):
    logged_in = wandb.login(relogin=True, key=dummy_api_key)
    assert logged_in is True
    logged_in = wandb.login()
    assert logged_in is True
