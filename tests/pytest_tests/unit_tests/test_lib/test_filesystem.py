import os
import platform
import shutil
import stat
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from wandb.sdk.lib.filesystem import copy_or_overwrite_changed, mkdir_exists_ok


def write_pause(path, content):
    """Append `content` to the file at path, flush the write, and wait 10ms.

    This ensures that file modification times are different for successive writes.
    """
    mode = "ab" if isinstance(path, bytes) else "a"
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    time.sleep(0.01)


@pytest.mark.parametrize("pathtype", [Path, str, bytes])
def test_mkdir_exists_ok_pathtypes(tmp_path, pathtype):
    """Test that mkdir_exists_ok works with all path-like objects."""
    new_dir = tmp_path / "new"
    mkdir_exists_ok(pathtype(new_dir))
    assert new_dir.is_dir()


def test_mkdir_exists_ok_existing(tmp_path):
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    mkdir_exists_ok(new_dir)
    assert new_dir.is_dir()


def test_mkdir_exists_ok_path_parents(tmp_path):
    new_dir = tmp_path / "a" / "b" / "c"
    mkdir_exists_ok(new_dir)
    assert new_dir.is_dir()


def test_mkdir_exists_ok_file_exists(tmp_path):
    file = tmp_path / "file"
    file.touch()
    with pytest.raises(FileExistsError):
        mkdir_exists_ok(file)
    assert file.is_file()


@pytest.mark.xfail(reason="Not possible to chown a file to root under test runner.")
def test_mkdir_exists_ok_not_writable(tmp_path):
    # Reference test: only works when run manually.
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    new_dir.chmod(0o700)
    shutil.chown(new_dir, user="root")

    with pytest.raises(PermissionError):
        mkdir_exists_ok(new_dir)


def test_copy_or_overwrite_changed_windows_colon(tmp_path):
    source_path = tmp_path / "new_file.txt"
    target_path = tmp_path / "file:with:colon.txt"

    source_path.write_text("original")
    final_path = copy_or_overwrite_changed(source_path, target_path)

    if platform.system() == "Windows":
        assert final_path == tmp_path / "file-with-colon.txt"
    else:
        assert final_path == target_path
    assert final_path.read_text() == "original"


def test_copy_or_overwrite_changed_no_copy(tmp_path):
    source_path = tmp_path / "new_file.txt"
    target_path = tmp_path / "target_file.txt"

    source_path.write_text("original")
    shutil.copy2(source_path, target_path)

    with patch("shutil.copy2") as copy2_mock:
        copy_or_overwrite_changed(source_path, target_path)
        assert not copy2_mock.called


def test_copy_or_overwrite_changed_overwite_different_mtime(tmp_path):
    source_path = tmp_path / "new_file.txt"
    target1_path = tmp_path / "target1.txt"
    target2_path = tmp_path / "target2.txt"

    write_pause(source_path, "new content")
    write_pause(target1_path, "old content 1")
    write_pause(target2_path, "old content 2")

    with patch("shutil.copy2") as copy2_mock:
        copy_or_overwrite_changed(source_path, target1_path)
        assert copy2_mock.call_count == 1
        copy_or_overwrite_changed(source_path, target2_path)
        assert copy2_mock.call_count == 2


@pytest.mark.parametrize("permissions", [0o666, 0o644, 0o444, 0o600, 0o400])
def test_copy_or_overwrite_changed_bad_permissions(tmp_path, permissions):
    source_path = tmp_path / "new_file.txt"
    target_path = tmp_path / "old_file.txt"

    write_pause(source_path, "replacement")
    write_pause(target_path, "original")
    os.chmod(target_path, permissions)

    dest_path = copy_or_overwrite_changed(source_path, target_path)
    assert dest_path == target_path
    assert dest_path.read_text() == "replacement"
    assert dest_path.stat().st_mode & stat.S_IWOTH == stat.S_IWOTH


@pytest.mark.xfail(reason="Not possible to chown a file to root under test runner.")
def test_copy_or_overwrite_changed_unfixable(tmp_path):
    # Reference test: only works when run manually.
    source_path = tmp_path / "new_file.txt"
    target_path = tmp_path / "old_file.txt"

    write_pause(source_path, "replacement")
    write_pause(target_path, "original")
    os.chmod(target_path, 0o600)
    shutil.chown(target_path, user="root")

    with pytest.raises(PermissionError) as e:
        copy_or_overwrite_changed(source_path, target_path)
    assert "Unable to overwrite" in str(e.value)
