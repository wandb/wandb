import os

import pytest
import wandb


def test_file_upload_good(wandb_backend_spy, mock_run, publish_util):
    run = mock_run(use_magic_mock=True)

    def begin_fn(interface):
        if not os.path.exists(run.dir):
            os.makedirs(run.dir)
        with open(os.path.join(run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    files = [dict(files_dict=dict(files=[("test.txt", "now")]))]
    publish_util(run, begin_cb=begin_fn, files=files)

    with wandb_backend_spy.freeze() as snapshot:
        assert "test.txt" in snapshot.uploaded_files(run_id=run.id)


@pytest.mark.parametrize(
    "x_primary_node, files",
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
        (False, set()),
    ],
)
@pytest.mark.wandb_core_only
def test_upload_wandb_files(user, wandb_backend_spy, x_primary_node, files):
    with wandb.init(settings=wandb.Settings(x_primary_node=x_primary_node)) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        uploaded_files = set(snapshot.uploaded_files(run_id=run.id))
        assert files == uploaded_files
