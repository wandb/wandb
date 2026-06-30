import ctypes
import errno
import os
import platform
import re
import shutil
import time
from pathlib import Path
from unittest import mock
from unittest.mock import Mock, patch

import pytest

# from pyfakefs.fake_filesystem import OSType
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.filesystem import (
    are_paths_on_same_drive,
    check_exists,
    copy_or_overwrite_changed,
    mkdir_allow_fallback,
    mkdir_exists_ok,
    reflink,
    system_preferred_path,
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


def test_copy_or_overwrite_changed_overwrite_different_mtime(tmp_path):
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
    umask = os.umask(0o022)
    assert dest_path.stat().st_mode & umask == 0


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


@pytest.mark.xfail(reason="Fails on file systems that don't support reflinks")
def test_reflink_success(tmp_path):
    target_path = tmp_path / "target.txt"
    link_path = tmp_path / "link.txt"

    target_content = b"test content"
    new_content = b"new content"
    target_path.write_bytes(target_content)

    reflink(target_path, link_path)
    # The linked file should have the same content.
    assert link_path.read_bytes() == target_content

    link_path.write_bytes(new_content)
    # The target file should not change when the linked file is modified.
    assert target_path.read_bytes() == target_content

    with pytest.raises(FileExistsError):
        reflink(target_path, link_path)

    reflink(target_path, link_path, overwrite=True)
    assert link_path.read_bytes() == target_content


@pytest.mark.parametrize(
    "errno_code, expected_exception",
    [
        (errno.EPERM, PermissionError),
        (errno.EACCES, PermissionError),
        (errno.ENOENT, FileNotFoundError),
        (errno.EXDEV, ValueError),
        (errno.EISDIR, IsADirectoryError),
        (errno.EOPNOTSUPP, OSError),
        (errno.ENOTSUP, OSError),
        (errno.EINVAL, ValueError),
        (errno.EFAULT, OSError),
    ],
)
@pytest.mark.skipif(
    platform.system() == "Windows", reason="We don't support reflinks on Windows"
)
def test_reflink_errors(errno_code, expected_exception, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError(errno_code, os.strerror(errno_code))

    monkeypatch.setattr(filesystem, "_reflink_linux", fail)
    monkeypatch.setattr(filesystem, "_reflink_macos", fail)

    with pytest.raises(expected_exception):
        reflink("target", "link")


@pytest.mark.skipif(
    platform.system() == "Windows", reason="We don't support reflinks on Windows"
)
def test_reflink_file_exists_error(tmp_path):
    target_path = tmp_path / "target.txt"
    link_path = tmp_path / "link.txt"
    target_path.write_bytes(b"content1")
    link_path.write_bytes(b"content2")

    with pytest.raises(FileExistsError):
        reflink(target_path, link_path)


@pytest.mark.parametrize(
    "system, exception",
    [
        ("Linux", ValueError("Called _reflink_linux")),
        ("Darwin", ValueError("Called _reflink_macos")),
        ("Other", OSError(errno.ENOTSUP, "reflinks are not supported on Other")),
    ],
)
def test_reflink_platform_dispatch(monkeypatch, system, exception):
    def _reflink_linux(*args, **kwargs):
        raise ValueError("Called _reflink_linux")

    def _reflink_macos(*args, **kwargs):
        raise ValueError("Called _reflink_macos")

    monkeypatch.setattr(filesystem, "_reflink_linux", _reflink_linux)
    monkeypatch.setattr(filesystem, "_reflink_macos", _reflink_macos)
    monkeypatch.setattr(platform, "system", lambda: system)

    with pytest.raises(type(exception), match=re.escape(str(exception))):
        reflink("target", "link")


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS specific code")
def test_reflink_macos_cross_device(monkeypatch, example_file):
    def clonefile_cross_device(*args, **kwargs):
        return errno.EXDEV

    def cdll_cross_device(*args, **kwargs):
        clib = Mock()
        clib.clonefile = clonefile_cross_device
        return clib

    monkeypatch.setattr(ctypes, "CDLL", cdll_cross_device)
    monkeypatch.setattr(ctypes, "get_errno", clonefile_cross_device)

    with pytest.raises(ValueError, match="Cannot link across filesystems"):
        reflink(example_file, "link_file")


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS specific code")
def test_reflink_macos_corner_cases(monkeypatch, example_file):
    def cdll_bad_fallback(module, *args, **kwargs):
        if module == "libc.dylib":
            raise FileNotFoundError
        return None

    monkeypatch.setattr(ctypes, "CDLL", cdll_bad_fallback)

    with pytest.raises(OSError, match="does not support reflinks"):
        reflink(example_file, "link_file")

    def cdll_weird_fallback(*args, **kwargs):
        raise RuntimeError("Something went wrong")

    monkeypatch.setattr(ctypes, "CDLL", cdll_weird_fallback)

    with pytest.raises(RuntimeError, match="Something went wrong"):
        reflink(example_file, "link_file")


@pytest.mark.skipif(platform.system() == "Windows", reason="':' not allowed in paths.")
def test_check_exists(tmp_path):
    path_with_colon = tmp_path / "file:name.txt"
    path_with_dash = tmp_path / "file-name.txt"

    assert check_exists(path_with_colon) is None

    path_with_colon.touch()
    assert check_exists(path_with_colon) == path_with_colon

    path_with_colon.unlink()
    path_with_dash.touch()
    assert check_exists(path_with_colon) == path_with_dash

    path_with_colon.touch()
    assert check_exists(path_with_colon) == path_with_colon


def test_system_preferred_path():
    path = "C:/path:with:colon.txt"
    windows = "C:/path-with-colon.txt"
    if platform.system() == "Windows":
        assert system_preferred_path(path) == windows
    else:
        assert system_preferred_path(path) == path


def test_system_preferred_path_warning(wandb_caplog):
    path = Path("path:with/colon.txt")
    with mock.patch("platform.system", return_value="Windows"):
        system_preferred_path(path, warn=True)
        assert f"Replacing ':' in {path} with '-'" in wandb_caplog.text


def test_mkdir_allow_fallback_success(tmp_path):
    dir_name = tmp_path / "valid" / "directory"
    assert mkdir_allow_fallback(dir_name) == dir_name
    assert dir_name.exists()


def test_mkdir_allow_fallback_with_problematic_chars(tmp_path):
    dir_name = tmp_path / "pr\0blematic:directory*with<chars"
    result_dir = mkdir_allow_fallback(dir_name)
    assert result_dir.is_dir()


def test_mkdir_allow_fallback_with_unexpected_error(tmp_path):
    with mock.patch("os.makedirs", side_effect=OSError(1, "Unexpected error")):
        with pytest.raises(OSError, match="Unexpected error"):
            mkdir_allow_fallback("some_directory")


def test_mkdir_allow_fallback_with_uncreatable_directory(tmp_path):
    dir_name = tmp_path / "uncreatable" / "directory"
    with mock.patch("os.makedirs", side_effect=OSError(22, "Invalid argument")):
        with pytest.raises(OSError, match="Unable to create directory"):
            mkdir_allow_fallback(dir_name)


def test_mkdir_allow_fallback_with_warning(wandb_caplog, tmp_path):
    dir_name = tmp_path / "direct\0ry"
    new_name = tmp_path / "direct-ry"
    assert mkdir_allow_fallback(dir_name) == new_name
    assert f"Creating '{new_name}' instead of '{dir_name}'" in wandb_caplog.text


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="Drive letters are only relevant on Windows",
)
@pytest.mark.parametrize(
    "path1,path2,expected",
    [
        (Path("C:\\foo"), Path("C:\\bar"), True),
        (Path("C:\\foo"), Path("D:\\bar"), False),
    ],
)
def test_are_windows_paths_on_same_drive(path1, path2, expected):
    assert are_paths_on_same_drive(path1, path2) == expected
