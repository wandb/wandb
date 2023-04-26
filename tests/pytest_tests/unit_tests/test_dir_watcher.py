"""dir_watcher tests."""

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from unittest.mock import Mock, patch

import pytest
import wandb.filesync.dir_watcher
from wandb.filesync.dir_watcher import DirWatcher
from wandb.sdk.internal.file_pusher import FilePusher

if TYPE_CHECKING:
    pass


@pytest.fixture
def file_pusher():
    return Mock()


@pytest.fixture
def settings():
    return Mock(ignore_globs=[])


@pytest.fixture
def tempdir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def dir_watcher(settings, file_pusher, tempdir: Path) -> DirWatcher:
    with patch.object(wandb.filesync.dir_watcher, "wd_polling", Mock()):
        yield DirWatcher(
            settings=settings,
            file_pusher=file_pusher,
            file_dir=str(tempdir),
        )


def write_with_mtime(path: Path, content: bytes, mtime: int) -> None:
    path.write_bytes(content)
    os.utime(str(path), (mtime, mtime))


@pytest.mark.parametrize(
    ["write_file", "expect_called"],
    [
        (lambda f: write_with_mtime(f, b"content", mtime=0), True),
        (lambda f: write_with_mtime(f, b"", mtime=0), False),
        (lambda f: None, False),
    ],
)
def test_dirwatcher_update_policy_live_calls_file_changed_iff_file_nonempty(
    tempdir: Path,
    file_pusher: FilePusher,
    dir_watcher: DirWatcher,
    write_file: Callable[[Path], None],
    expect_called: bool,
):
    """Test that if a file exists, the update policy is called."""
    f = tempdir / "my-file.txt"
    write_file(f)
    dir_watcher.update_policy(str(f), "live")
    assert file_pusher.file_changed.called == expect_called
