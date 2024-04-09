from unittest.mock import MagicMock, patch

import pytest
from wandb.errors import WandbCoreNotAvailableError
from wandb.util import get_core_path


def test_wandb_core_dev_mode():
    """Test dev mode, both with and without requiring wandb_core."""
    mocked_path = "/path/to/core"
    with patch("os.environ", {"_WANDB_CORE_PATH": mocked_path}):
        path = get_core_path()

    assert path == mocked_path


def mocked_wandb_core(version, path):
    return MagicMock(
        __version__=version,
        get_core_path=MagicMock(return_value=path),
    )


def test_wandb_core_installed_compatibly_version():
    """Test that when wandb_core is required, and the installed version is compatible, we return the path."""
    version = "0.10.0"
    mocked_path = "/path/to/core"

    with patch("wandb.__core_version__", version), patch(
        "wandb.util.get_module",
        return_value=mocked_wandb_core(version, mocked_path),
    ):
        path = get_core_path()

    assert path == mocked_path


def test_wandb_core_installed_incompatibly_version():
    """Test that when wandb_core is required, but the installed version is incompatible, we raise an exception."""
    with patch("wandb.__core_version__", "0.10.0"), patch(
        "wandb.util.get_module",
        return_value=mocked_wandb_core(
            "0.11.0",
            "/path/to/core",
        ),
    ):
        with pytest.raises(ImportError):
            get_core_path()


def test_wandb_core_not_installed():
    """Test that when wandb_core is required, but not installed, we raise an exception."""

    class TestError(Exception):
        pass

    with patch("wandb.util.get_module", side_effect=TestError):
        with pytest.raises(TestError):
            get_core_path()


def test_wandb_core_installed_no_op():
    """Test that when wandb_core is required, and the installed version is no-op, we raise an exception."""
    version = "0.10.0"
    with patch("wandb.__core_version__", version), patch(
        "wandb.util.get_module",
        return_value=mocked_wandb_core(
            version,
            "",
        ),
    ):
        with pytest.raises(WandbCoreNotAvailableError):
            get_core_path()
