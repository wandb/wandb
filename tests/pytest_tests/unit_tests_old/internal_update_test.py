"""
wandb/internal/update.py test.
"""

import sys
from unittest import mock

import pytest  # type: ignore
import wandb

update = wandb.wandb_sdk.internal.update


def test_check_nothing_new(mock_server):
    package = update._find_available(wandb.__version__)
    assert package is None


def test_check_prerelease_avail(mock_server):
    latest_version, pip_prerelease, _, _, _ = update._find_available("88.1.2rc3")
    assert (latest_version, pip_prerelease) == ("88.1.2rc12", True)


def test_check_nextrelease_after_pre_avail(mock_server):
    latest_version, pip_prerelease, _, _, _ = update._find_available("0.0.8rc3")
    assert (latest_version, pip_prerelease) == (wandb.__version__, False)


def test_check_nextrelease_avail(mock_server):
    latest_version, pip_prerelease, _, _, _ = update._find_available("0.0.6")
    assert (latest_version, pip_prerelease) == (wandb.__version__, False)


def test_check_deleted(mock_server):
    (
        latest_version,
        pip_prerelease,
        deleted,
        yanked,
        yanked_message,
    ) = update._find_available("0.0.4")
    assert (latest_version, pip_prerelease) == (wandb.__version__, False)
    assert deleted is True
    assert yanked is False
    assert yanked_message is None


def test_check_yanked(mock_server):
    (
        latest_version,
        pip_prerelease,
        deleted,
        yanked,
        yanked_message,
    ) = update._find_available("0.0.2")
    assert (latest_version, pip_prerelease) == (wandb.__version__, False)
    assert deleted is False
    assert yanked is True
    assert yanked_message is None


def test_check_yanked_reason(mock_server):
    (
        latest_version,
        pip_prerelease,
        deleted,
        yanked,
        yanked_message,
    ) = update._find_available("0.0.3")
    assert (latest_version, pip_prerelease) == (wandb.__version__, False)
    assert deleted is False
    assert yanked is True
    assert yanked_message == "just cuz"


def test_pypi_check_nothing_new(mock_server):
    update.check_available(wandb.__version__)
    assert mock_server.ctx["json"] is not None


def test_pypi_check_avail(mock_server):
    update.check_available("0.0.1")
    assert mock_server.ctx["json"] is not None
