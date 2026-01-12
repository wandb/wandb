from __future__ import annotations

import wandb


def test_uploads_at_end(wandb_backend_spy, tmp_path):
    file = tmp_path / "my_test_dir" / "my_test_file.txt"
    file.parent.mkdir()
    file.write_text("testing testing")

    with wandb.init() as run:
        run.save(file, policy="end")

    with wandb_backend_spy.freeze() as snapshot:
        assert "my_test_dir/my_test_file.txt" in snapshot.uploaded_files(
            run_id=run.id,
        )
