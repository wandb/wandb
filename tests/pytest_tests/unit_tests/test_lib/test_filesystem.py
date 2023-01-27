from pathlib import Path

import pytest
from wandb.sdk.lib.filesystem import mkdir_exists_ok


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


@pytest.mark.xfail(reason="os.access(os.W_OK) appears to not be reliable?")
def test_mkdir_exists_ok_not_writable(tmp_path):
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    new_dir.chmod(0o444)

    with pytest.raises(PermissionError):
        mkdir_exists_ok(new_dir)
