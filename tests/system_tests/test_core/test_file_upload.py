from __future__ import annotations

import pathlib
import platform

import pytest
import wandb

from tests.fixtures.wandb_backend_spy import WandbBackendSpy

# Special W&B files created and uploaded by a primary node.
_WANDB_FILES_PRIMARY = (
    "wandb-metadata.json",
    "wandb-summary.json",
    "output.log",
    "config.yaml",
    "requirements.txt",
)

# Special W&B files created and uploaded by a non-primary node.
#
# A run in "shared" mode is written to by multiple nodes (machines, processes,
# etc.) simultaneously. To avoid nodes overwriting each others' data, a single
# user-designated "primary" node uploads special files.
_WANDB_FILES_NOT_PRIMARY = ("output.log",)


@pytest.mark.parametrize(
    "x_primary, files",
    (
        (True, _WANDB_FILES_PRIMARY),
        (False, _WANDB_FILES_NOT_PRIMARY),
    ),
)
def test_creates_and_uploads_wandb_files(
    x_primary: bool,
    files: tuple[str, ...],
    wandb_backend_spy: WandbBackendSpy,
):
    with wandb.init(settings=wandb.Settings(x_primary=x_primary)) as run:
        print("SWEET")

    for file in files:
        assert pathlib.Path(run.dir, file).exists()
    with wandb_backend_spy.freeze() as snapshot:
        assert set(files) == set(snapshot.uploaded_files(run_id=run.id))


@pytest.mark.parametrize(
    "x_primary, files",
    (
        (True, _WANDB_FILES_PRIMARY),
        (False, _WANDB_FILES_NOT_PRIMARY),
    ),
)
def test_creates_wandb_files_when_offline(
    x_primary: bool,
    files: tuple[str, ...],
):
    with wandb.init(
        mode="offline",
        settings=wandb.Settings(x_primary=x_primary),
    ) as run:
        print("SWEET")

    for file in files:
        assert pathlib.Path(run.dir, file).exists()


@pytest.mark.parametrize(
    "x_label, files",
    [
        ("valid_label", {"output_valid_label.log"}),
        ("invalid?:label<>", {"output_invalid__label_.log"}),
    ],
)
@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
def test_upload_wandb_files_windows_with_label(wandb_backend_spy, x_label, files):
    with wandb.init(
        settings=wandb.Settings(x_label=x_label, x_primary=False),
    ) as run:
        print("SWEET")

    with wandb_backend_spy.freeze() as snapshot:
        assert files == set(snapshot.uploaded_files(run_id=run.id))


@pytest.mark.parametrize(
    "x_label, files",
    [
        ("valid_label", {"output_valid_label.log"}),
        ("invalid/label", {"output_invalid_label.log"}),
    ],
)
@pytest.mark.skipif(platform.system() != "Windows", reason="Linux only")
def test_upload_wandb_files_non_windows_with_label(wandb_backend_spy, x_label, files):
    with wandb.init(
        settings=wandb.Settings(x_label=x_label, x_primary=False),
    ) as run:
        print("SWEET")

    with wandb_backend_spy.freeze() as snapshot:
        assert files == set(snapshot.uploaded_files(run_id=run.id))
