from __future__ import annotations

import platform

import pytest
import wandb


@pytest.mark.parametrize(
    "x_primary, files",
    [
        (
            True,
            {
                "wandb-metadata.json",
                "wandb-summary.json",
                "output.log",
                "config.yaml",
                "requirements.txt",
            },
        ),
        (False, {"output.log"}),
    ],
)
def test_upload_wandb_files(wandb_backend_spy, x_primary, files):
    with wandb.init(settings=wandb.Settings(x_primary=x_primary)) as run:
        print("SWEET")

    with wandb_backend_spy.freeze() as snapshot:
        uploaded_files = set(snapshot.uploaded_files(run_id=run.id))
        assert files == uploaded_files


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
