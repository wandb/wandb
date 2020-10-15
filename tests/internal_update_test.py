"""
wandb/internal/update.py test.
"""

import pytest  # type: ignore

import wandb
from wandb.internal import update


def test_check_nothing_new(mock_server):
    package = update._find_available(wandb.__version__)
    assert package is None


def test_check_prerelease_avail(mock_server):
    package = update._find_available("88.1.2rc3")
    assert package == ("88.1.2rc12", True)


def test_check_nextrelease_after_pre_avail(mock_server):
    package = update._find_available("0.0.8rc3")
    assert package == (wandb.__version__, False)


def test_check_nextrelease_avail(mock_server):
    package = update._find_available("0.0.6")
    assert package == (wandb.__version__, False)


def test_pypi_check_nothing_new(mock_server):
     update.check_available(wandb.__version__)
     assert mock_server.ctx["json"] is not None


def test_pypi_check_avail(mock_server):
     update.check_available("0.0.1")
     assert mock_server.ctx["json"] is not None
