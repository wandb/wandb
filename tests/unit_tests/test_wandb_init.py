import os
import platform
import tempfile

import pytest
import wandb


@pytest.mark.skipif(
    platform.system() == "Linux",
    reason=(
        "For tests run in CI on linux, the runas user is root. "
        "This means that the test can always write to the root dir, "
        "even if permissions are set to read only."
    ),
)
def test_run_create_root_dir_without_permissions_defaults_to_temp_dir(tmp_path):
    temp_dir = tempfile.gettempdir()
    root_dir = tmp_path / "no_permissions_test"
    root_dir.mkdir(parents=True, mode=0o444, exist_ok=True)

    with wandb.init(
        settings=wandb.Settings(root_dir=os.path.join(root_dir, "missing")),
        mode="offline",
    ) as run:
        run.log({"test": 1})

    assert not os.path.exists(os.path.join(root_dir, "missing"))
    assert run.settings.root_dir == temp_dir


def test_run_create_root_dir_exists_without_permissions(tmp_path, monkeypatch):
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
