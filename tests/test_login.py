"""
login tests.
"""

import time

import wandb


def test_login_timeout(mock_tty):
    mock_tty("junk\nmore\n")
    start_time = time.time()
    ret = wandb.login(timeout=4)
    elapsed = time.time() - start_time
    assert 2 < elapsed < 6
    assert ret is False
    assert wandb.api.api_key is None
