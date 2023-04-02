import os
import platform
import shutil
import stat
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from wandb.sdk.lib.filesystem import (
    copy_or_overwrite_changed,
    mkdir_exists_ok,
    safe_open,
)


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


@pytest.mark.parametrize("binary", ["", "b", "t"])
@pytest.mark.parametrize("mode", ["w", "w+", "a", "a+"])
def test_safe_write_interrupted_overwrites(binary, mode):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir = Path(tmp_dir)
        original_file = tmp_dir / "original.txt"
        original_content = "Original content 🧐"
        original_file.write_text(original_content, encoding="utf-8")

        with pytest.raises(RuntimeError):
            with safe_open(original_file, mode + binary) as f:
                f.write(b"!!!" if binary == "b" else "!!!")
                raise RuntimeError("Interrupted write")

        assert original_file.read_text("utf-8") == original_content
        assert list(tmp_dir.iterdir()) == [original_file]


@pytest.mark.parametrize("binary", ["", "b", "t"])
@pytest.mark.parametrize("mode", ["w", "w+"])
def test_safe_write_complete_overwrites(mode, binary):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir = Path(tmp_dir)
        original_file = tmp_dir / "original.txt"
        original_file.write_text("Original content")
        new_content = "New content 😐"  # Shorter than original.

        encoding = "utf-8" if binary != "b" else None
        with safe_open(original_file, mode + binary, encoding=encoding) as f:
            f.write(new_content.encode("utf-8") if binary == "b" else new_content)

        assert original_file.read_text("utf-8") == new_content
        assert list(tmp_dir.iterdir()) == [original_file]


@pytest.mark.parametrize("binary", ["", "b", "t"])
@pytest.mark.parametrize("mode", ["a", "a+"])
def test_safe_write_complete_appends(binary, mode):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir = Path(tmp_dir)
        original_file = tmp_dir / "original.txt"
        original_content = "Original content 🧐"
        original_file.write_text(original_content, encoding="utf-8")
        new_content = "New content❗"

        encoding = "utf-8" if binary != "b" else None
        with safe_open(original_file, mode + binary, encoding=encoding) as f:
            f.write(new_content.encode("utf-8") if binary == "b" else new_content)

        assert original_file.read_text("utf-8") == original_content + new_content
        assert list(tmp_dir.iterdir()) == [original_file]


@pytest.mark.parametrize("binary", ["", "b", "t"])
@pytest.mark.parametrize("mode", ["r", "r+"])
def test_safe_read_missing_file(tmp_path, binary, mode):
    missing_file = tmp_path / "missing.txt"

    with pytest.raises(FileNotFoundError):
        with safe_open(missing_file, mode + binary):
            pass


@pytest.mark.parametrize("binary", ["", "b", "t"])
def test_safe_read_existing_file(tmp_path, binary):
    existing_file = tmp_path / "existing.txt"
    original_content = "Original content 🧐"
    existing_file.write_text(original_content, encoding="utf-8")

    encoding = "utf-8" if binary != "b" else None
    with safe_open(existing_file, "r" + binary, encoding=encoding) as f:
        content = f.read()
        if binary == "b":
            content = content.decode("utf-8")
        assert content == original_content


@pytest.mark.parametrize("binary", ["", "b", "t"])
def test_safe_read_write_existing_file(binary):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir = Path(tmp_dir)
        original_file = tmp_dir / "original.txt"
        original_content = "🔜Original content"
        original_file.write_text(original_content, encoding="utf-8")
        new_content = "More❗"

        encoding = "utf-8" if binary != "b" else None
        with safe_open(original_file, "r+" + binary, encoding=encoding) as f:
            content = f.read()
            if binary == "b":
                content = content.decode("utf-8")
            assert content == original_content
            f.seek(5)
            f.write(new_content.encode("utf-8") if binary == "b" else new_content)

        assert original_file.read_text("utf-8") == "🔜OMore❗ content"
        assert list(tmp_dir.iterdir()) == [original_file]


@pytest.mark.parametrize("binary", ["", "b", "t"])
@pytest.mark.parametrize("mode", ["x", "x+"])
def test_safe_exclusive_write_existing_file(tmp_path, binary, mode):
    existing_file = tmp_path / "existing.txt"
    existing_file.write_text("Existing content 🧐", encoding="utf-8")

    with pytest.raises(FileExistsError):
        with safe_open(existing_file, mode + binary):
            pass


@pytest.mark.parametrize("binary", ["", "b", "t"])
@pytest.mark.parametrize("mode", ["a", "a+", "x", "x+"])
def test_safe_write_interrupted_exclusive_writes(binary, mode):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir = Path(tmp_dir)
        original_file = tmp_dir / "original.txt"

        with pytest.raises(RuntimeError):
            with safe_open(original_file, mode + binary) as f:
                f.write(b"!!!" if binary == "b" else "!!!")
                raise RuntimeError("Interrupted write")

        assert not original_file.exists()
        assert list(tmp_dir.iterdir()) == []


@pytest.mark.parametrize("binary", ["", "b", "t"])
@pytest.mark.parametrize("mode", ["a", "a+", "x", "x+"])
def test_safe_write_complete_exclusive_writes(binary, mode):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir = Path(tmp_dir)
        original_file = tmp_dir / "original.txt"
        new_content = "New content 👾"

        encoding = "utf-8" if binary != "b" else None
        with safe_open(original_file, mode + binary, encoding=encoding) as f:
            f.write(new_content.encode("utf-8") if binary == "b" else new_content)

        assert original_file.read_text("utf-8") == new_content
        assert list(tmp_dir.iterdir()) == [original_file]
