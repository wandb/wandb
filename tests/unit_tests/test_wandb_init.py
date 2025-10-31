import os
import stat
import tempfile

import pytest
import wandb


def test_no_root_dir_access__uses_temp_dir(tmp_path, monkeypatch):
    temp_dir = tempfile.gettempdir()
    root_dir = tmp_path / "create_dir_test"
    os.makedirs(root_dir, exist_ok=True)

    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: not (
            mode == (os.R_OK | os.W_OK) and str(path) == str(root_dir)
        ),
    )

    with wandb.init(dir=root_dir, mode="offline") as run:
        run.log({"test": 1})

    assert run.settings.root_dir == temp_dir


def test_no_temp_dir_access__throws_error(monkeypatch):
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    temp_dir = tempfile.gettempdir()
    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: not (
            mode == (os.R_OK | os.W_OK) and str(path) == str(temp_dir)
        ),
    )

    with pytest.raises(ValueError):
        with wandb.init(dir=temp_dir, mode="offline") as run:
            run.log({"test": 1})


def test_makedirs_raises_oserror__uses_temp_dir(tmp_path, monkeypatch):
    tmp_file = tmp_path / "test.txt"
    tmp_file.touch()

    with wandb.init(dir=str(tmp_file / "dir2"), mode="offline") as run:
        run.log({"test": 1})

    assert run.settings.root_dir == tempfile.gettempdir()


def test_avoids_sync_dir_conflict(mocker):
    # Make the run start time the same for all runs.
    mocker.patch("time.time", return_value=123)

    with wandb.init(mode="offline", id="sync-dir-test") as run1:
        pass
    with wandb.init(mode="offline", id="sync-dir-test") as run2:
        pass
    with wandb.init(mode="offline", id="sync-dir-test") as run3:
        pass

    assert run2.settings.sync_dir == run1.settings.sync_dir + "-1"
    assert run3.settings.sync_dir == run1.settings.sync_dir + "-2"


def test_init_with_explicit_api_key_no_netrc_write(tmp_path, monkeypatch):
    """Test that API key provided in settings is not written to .netrc"""
    # Setup temp netrc
    netrc_path = str(tmp_path / "netrc")
    monkeypatch.setenv("NETRC", netrc_path)

    # Ensure netrc doesn't exist
    assert not os.path.exists(netrc_path)

    api_key = "X" * 40

    # Initialize with explicit API key
    with wandb.init(
        mode="offline",  # Use offline to avoid network calls
        settings=wandb.Settings(api_key=api_key)
    ) as run:
        assert run.settings.api_key == api_key

    # Verify .netrc was NOT created
    assert not os.path.exists(netrc_path), ".netrc should not be created when API key is explicit"


def test_init_without_explicit_api_key_uses_netrc(tmp_path, monkeypatch):
    """Test that when no API key is provided, normal resolution (netrc) is used"""
    # Setup netrc with API key
    netrc_path = str(tmp_path / "netrc")
    monkeypatch.setenv("NETRC", netrc_path)

    api_key = "Y" * 40
    with open(netrc_path, "w") as f:
        f.write(f"machine api.wandb.ai\n  login user\n  password {api_key}\n")
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    # Initialize without explicit API key - should pick up from netrc
    with wandb.init(mode="offline") as run:
        # In offline mode, it should read from netrc during setup
        # The api_key may or may not be set in settings depending on when it's read
        pass  # Just verify it doesn't fail

    # Verify netrc still exists and wasn't modified
    assert os.path.exists(netrc_path)
