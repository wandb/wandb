import glob
import os
import stat
import tempfile
import time

import pytest
import wandb


def test_no_root_dir_access__uses_temp_dir(tmp_path, monkeypatch):
    temp_dir = tempfile.gettempdir()
    root_dir = tmp_path / "create_dir_test"
    os.makedirs(root_dir, exist_ok=True)

    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: (
            not (mode == (os.R_OK | os.W_OK) and str(path) == str(root_dir))
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
        lambda path, mode: (
            not (mode == (os.R_OK | os.W_OK) and str(path) == str(temp_dir))
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


def test_temp_dir_cleanup_on_exit(tmp_path, monkeypatch):
    isolated_temp = tmp_path / "temp"
    isolated_temp.mkdir()
    monkeypatch.setenv("TMPDIR", str(isolated_temp))
    monkeypatch.setenv("TEMP", str(isolated_temp))
    monkeypatch.setenv("TMP", str(isolated_temp))
    monkeypatch.setattr(tempfile, "tempdir", str(isolated_temp))

    def list_paths():
        t = str(isolated_temp)
        pats = sorted(glob.glob(os.path.join(t, "wandb*")))
        out = []
        for p in pats:
            try:
                st = os.lstat(p)
                kind = (
                    "socket"
                    if stat.S_ISSOCK(st.st_mode)
                    else (
                        "dir"
                        if stat.S_ISDIR(st.st_mode)
                        else ("file" if stat.S_ISREG(st.st_mode) else "other")
                    )
                )
                out.append({"path": p, "kind": kind, "size": st.st_size})
            except FileNotFoundError:
                pass
        return out

    before = list_paths()

    run = wandb.init(
        id="temp-dir-cleanup-test",
        mode="offline",
        tags=["repro", "temp-sock", "cleanup", "offline"],
        config={"seed": 0},
    )
    run.log({"step": 0})
    run.finish()
    wandb.teardown()
    time.sleep(0.2)

    after = list_paths()

    new_items = [it for it in after if it not in before]
    assert len(new_items) == 0, (
        f"New items detected in temp directory after run.finish() and wandb.teardown(): {[f['path'] for f in new_items]}."
    )
