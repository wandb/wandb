import os
import platform
import shutil
import stat
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from pyfakefs.fake_filesystem import OSType
from wandb.sdk.lib.filesystem import (
    copy_or_overwrite_changed,
    mkdir_exists_ok,
    safe_copy,
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
            f.seek(len("🔜O".encode()))
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


def test_safe_copy_missing_source_file(tmp_path: Path):
    source_path = tmp_path / "missing.txt"
    target_path = tmp_path / "target.txt"

    with pytest.raises(FileNotFoundError):
        safe_copy(source_path, target_path)


def test_safe_copy_existing_source_and_target_files(tmp_path: Path):
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_content = "Source content 📝"
    target_content = "Target content 🎯"

    source_path.write_text(source_content, encoding="utf-8")
    target_path.write_text(target_content, encoding="utf-8")

    safe_copy(source_path, target_path)

    assert source_path.read_text("utf-8") == source_content
    assert target_path.read_text("utf-8") == source_content


def test_safe_copy_existing_source_and_missing_target(tmp_path: Path):
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_content = "Source content 📝"

    source_path.write_text(source_content, encoding="utf-8")

    returned = safe_copy(source_path, target_path)

    assert returned == target_path
    assert target_path.read_text("utf-8") == source_content


def test_safe_copy_str_path(tmp_path: Path):
    source_path = tmp_path / "source.txt"
    target_path = str(tmp_path / "target.txt")
    source_content = "Source content 📝"

    source_path.write_text(source_content, encoding="utf-8")

    returned = safe_copy(source_path, target_path)

    assert returned == target_path  # Should return str, not pathlib.Path.
    assert Path(target_path).read_text("utf-8") == source_content


real_temp_dir = tempfile.TemporaryDirectory()


@pytest.mark.skipif(sys.platform != "darwin", reason="pyfakefs limitations")
@pytest.mark.parametrize("fs_type", [OSType.LINUX, OSType.MACOS, OSType.WINDOWS])
def test_safe_copy_different_file_systems(fs, fs_type: OSType):
    fs.os = fs_type

    fs.add_real_directory(real_temp_dir.name)

    source_path = Path(real_temp_dir.name) / "source.txt"
    target_path = Path("/target.txt")
    source_content = "Source content 📝"

    source_path.write_text(source_content, encoding="utf-8")

    safe_copy(source_path, target_path)

    assert target_path.read_text("utf-8") == source_content


# I *think* this will work with the absurd copy function. If not, we can disable again.
# @pytest.mark.skipif(sys.platform == "win32", reason="Windows locks active files")
def test_safe_copy_target_file_changes_during_copy(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_content = "Source content 📝" * 1000
    changed_target_content = "Changed target content 🔀"

    source_path.write_text(source_content, encoding="utf-8")

    def repeatedly_write_content():
        end_time = time.time() + 1.0
        while time.time() < end_time:
            try:
                target_path.write_text(changed_target_content, encoding="utf-8")
            except PermissionError:
                pass

    def delayed_copy_with_pause(src, dst, *args, **kwargs):
        """Write a 4096 byte block at a time, pausing 0.1 seconds between writes."""
        # Windows often doesn't allow opening a file for writing while there is an open
        # file handle to it. To get around the PermissionError, we close the file
        # between writes, but also retry failed writes.
        pos = 0
        with open(src, "rb") as infile:
            for block in iter(lambda: infile.read(4096), b""):
                success = False
                while not success:
                    time.sleep(0.1)
                    try:
                        with open(dst, "wb") as outfile:
                            outfile.seek(pos)
                            outfile.write(block)
                        pos += len(block)
                        success = True
                    except PermissionError:
                        pass

    monkeypatch.setattr(shutil, "copy2", delayed_copy_with_pause)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(repeatedly_write_content)
        safe_copy(source_path, target_path)
        future.result()

    result_content = target_path.read_text("utf-8")
    assert result_content == source_content or result_content == changed_target_content


@pytest.mark.parametrize("src_link", [None, "symbolic", "hard"])
@pytest.mark.parametrize("dest_link", [None, "symbolic", "hard"])
def test_safe_copy_with_links(tmp_path: Path, src_link, dest_link):
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_content = "Source content 📝"
    target_content = "Target content 🎯"
    source_path.write_text(source_content, encoding="utf-8")
    target_path.write_text(target_content, encoding="utf-8")

    if src_link == "symbolic":
        use_src_path = source_path.with_suffix(".symlink")
        use_src_path.symlink_to(source_path)
    elif src_link == "hard":
        use_src_path = source_path.with_suffix(".hardlink")
        os.link(source_path, use_src_path)
    else:
        use_src_path = source_path
    source_path = use_src_path

    if dest_link == "symbolic":
        use_dst_path = target_path.with_suffix(".symlink")
        use_dst_path.symlink_to(target_path)
    elif dest_link == "hard":
        use_dst_path = target_path.with_suffix(".hardlink")
        os.link(target_path, use_dst_path)
    else:
        use_dst_path = target_path
    target_path = use_dst_path

    safe_copy(source_path, target_path)

    assert target_path.read_text("utf-8") == source_content
