"""Test executing notebooks against running Jupyter servers."""

from __future__ import annotations

import nbformat


def test_jupyter_server_code_saving(wandb_backend_spy, jupyter_server, notebook_client):
    notebook_name = "test_metadata.ipynb"
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_code_cell(
            """
                    import wandb

                    with wandb.init(project="test_project", save_code=True) as run:
                        run.log({"test": 1})
                    """
        ),
    ]
    with open(jupyter_server.root_dir / notebook_name, "w") as f:
        nbformat.write(nb, f)
    session_id, kernel_id = jupyter_server.create_session(notebook_path=notebook_name)
    client = notebook_client(notebook_path=notebook_name)

    client.execute_notebook(nb)
    client.nb_client.stop_channels()

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1, f"Expected 1 run, got {len(run_ids)}"
        run_id = run_ids.pop()
        saved_files = snapshot.uploaded_files(run_id=run_id)
        assert "code/test_metadata.ipynb" in saved_files


def test_jupyter_server_code_saving_nested_notebook(
    wandb_backend_spy, jupyter_server, notebook_client
):
    notebook_name = "test_metadata.ipynb"
    nb_dir = jupyter_server.root_dir / "nested"
    nb_dir.mkdir(parents=True, exist_ok=True)
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_code_cell(
            """
                import wandb

                with wandb.init(project="test_project", save_code=True) as run:
                    run.log({"test": 1})
                """
        ),
    ]
    with open(nb_dir / notebook_name, "w") as f:
        nbformat.write(nb, f)

    session_id, kernel_id = jupyter_server.create_session(
        notebook_path=f"nested/{notebook_name}"
    )
    client = notebook_client(notebook_path=f"nested/{notebook_name}")

    client.execute_notebook(nb)
    client.nb_client.stop_channels()

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1, f"Expected 1 run, got {len(run_ids)}"
        run_id = run_ids.pop()
        saved_files = snapshot.uploaded_files(run_id=run_id)
        assert "code/nested/test_metadata.ipynb" in saved_files
