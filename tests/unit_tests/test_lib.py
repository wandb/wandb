import os
import platform
import shutil
import stat
from unittest.mock import patch

from wandb import wandb_lib
from wandb.sdk.lib.filesystem import copy_or_overwrite_changed


def test_write_netrc():
    api_key = "X" * 40
    res = wandb_lib.apikey.write_netrc("http://localhost", "vanpelt", api_key)
    assert res
    with open(os.path.expanduser("~/.netrc")) as f:
        assert f.read() == (
            "machine localhost\n" "  login vanpelt\n" "  password %s\n" % api_key
        )


def test_write_netrc_invalid_host():
    api_key = "X" * 40
    res = wandb_lib.apikey.write_netrc("http://foo", "vanpelt", api_key)
    assert res is None


def test_copy_or_overwrite_changed_windows_colon(tmp_path):
    source_path = tmp_path / "original_file"
    target_path = tmp_path / "file:with:colon"

    source_path.write_text("original")
    final_path = copy_or_overwrite_changed(source_path, target_path)

    if platform.system() == "Windows":
        assert final_path == tmp_path / "file-with-colon"
    else:
        assert final_path == target_path
    assert final_path.read_text() == "original"


def test_copy_or_overwrite_changed_no_copy(tmp_path):
    source_path = tmp_path / "original_file"
    target_path = tmp_path / "target_file"

    source_path.write_text("original")
    shutil.copy2(source_path, target_path)

    with patch("shutil.copy2") as copy2_mock:
        copy_or_overwrite_changed(source_path, target_path)
        assert not copy2_mock.called


def test_copy_or_overwrite_changed_overwite_different_mtime(tmp_path):
    source_path = tmp_path / "original_file"
    target1_path = tmp_path / "target1"
    target2_path = tmp_path / "target2"

    target1_path.write_text("text")
    source_path.write_text("text")
    target2_path.write_text("text")

    with patch("shutil.copy2") as copy2_mock:
        copy_or_overwrite_changed(source_path, target1_path)
        assert copy2_mock.call_count == 1
        copy_or_overwrite_changed(source_path, target2_path)
        assert copy2_mock.call_count == 2


def test_copy_or_overwrite_changed_bad_permissions(tmp_path):
    source_path = tmp_path / "original_file"
    target_path = tmp_path / "target_file"

    source_path.write_text("original")
    target_path.write_text("altered")
    os.chmod(target_path, 0o600)

    dest_path = copy_or_overwrite_changed(source_path, target_path)
    assert dest_path.stat().st_mode & stat.S_IWOTH == stat.S_IWOTH
    assert dest_path.read_text() == "original", dest_path.stat().st_mode
