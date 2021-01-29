import os
import platform
import pytest
import sys
import time


pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 5) or platform.system() == "Windows",
    reason="Our notebook fixture only works in py3, windows was flaking",
)


def test_one_cell(notebook):
    with notebook("one_cell.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output(0)
        print(output)
        assert "lovely-dawn-32" in output[-1]["data"]["text/html"]
        # assert "Failed to query for notebook name" not in text


def test_magic(notebook):
    with notebook("magic.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output(1)
        print(output)
        assert notebook.base_url in output[0]["data"]["text/html"]


def test_code_saving(notebook, live_mock_server):
    # TODO: this is awfully slow, we should likely run these in parallel
    with notebook("code_saving.ipynb") as nb:
        nb.execute_all()
        server_ctx = live_mock_server.get_ctx()
        artifact_name = list(server_ctx["artifacts"].keys())[0]
        # We run 3 cells after calling wandb.init
        assert len(server_ctx["artifacts"][artifact_name]) == 3

    with notebook("code_saving.ipynb", save_code=False) as nb:
        nb.execute_all()
        assert "Failed to detect the name of this notebook" in nb.all_output_text()

    # Let's make sure we warn the user if they lie to us.
    with notebook("code_saving.ipynb") as nb:
        os.remove("code_saving.ipynb")
        nb.execute_all()
        assert "WANDB_NOTEBOOK_NAME should be a path" in nb.all_output_text()
