import io
import os
import pathlib
import shutil
from contextlib import contextmanager
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import nbformat
import pytest
import wandb
import wandb.util
from nbclient import NotebookClient
from nbclient.client import CellExecutionError
from wandb.sdk.lib.ipython import PythonType

# wandb.jupyter is lazy loaded, so we need to force it to load
# before we can monkeypatch it
wandb.jupyter.quiet()


@pytest.fixture
def mocked_module(monkeypatch):
    """This allows us to mock modules loaded via wandb.util.get_module."""

    def mock_get_module(module):
        orig_get_module = wandb.util.get_module
        mocked_module = MagicMock()

        def get_module(mod):
            if mod == module:
                return mocked_module
            else:
                return orig_get_module(mod)

        monkeypatch.setattr(wandb.util, "get_module", get_module)
        return mocked_module

    return mock_get_module


@pytest.fixture
def mocked_ipython():
    def run_cell(cell):
        print("Running cell: ", cell)
        exec(cell)

    with patch("wandb.sdk.lib.ipython._get_python_type") as ipython_get_type, patch(
        "wandb.sdk.wandb_settings._get_python_type"
    ) as settings_get_type:
        ipython_get_type.return_value = "jupyter"
        settings_get_type.return_value = "jupyter"
        html_mock = MagicMock()
        with patch("wandb.sdk.lib.ipython.display_html", html_mock):
            ipython = MagicMock()
            ipython.html = html_mock
            ipython.run_cell = run_cell
            # TODO: this is really unfortunate, for reasons not clear to me, monkeypatch doesn't work
            orig_get_ipython = wandb.jupyter.get_ipython
            orig_display = wandb.jupyter.display
            wandb.jupyter.get_ipython = lambda: ipython
            wandb.jupyter.display = lambda obj: html_mock(obj._repr_html_())
            yield ipython
            wandb.jupyter.get_ipython = orig_get_ipython
            wandb.jupyter.display = orig_display


class WandbNotebookClient(NotebookClient):
    def execute_all(self, store_history: bool = True) -> list:
        executed_cells = []

        for idx, cell in enumerate(self.nb.cells):
            # the first cell is the setup cell
            nb_cell_id = idx + 1
            try:
                # print(cell)
                executed_cell = super().execute_cell(
                    cell=cell,
                    cell_index=idx,
                    store_history=False if idx == 0 else store_history,
                )
            except CellExecutionError as e:
                print("Cell output before exception:")
                print("=============================")
                for output in cell["outputs"]:
                    if output["output_type"] == "stream":
                        print(output["text"])
                raise e
            for output in executed_cell["outputs"]:
                if output["output_type"] == "error" and nb_cell_id != 0:
                    print("Error in cell: %d" % nb_cell_id)
                    print("\n".join(output["traceback"]))
                    raise ValueError(output["evalue"])
            executed_cells.append(executed_cell)

        return executed_cells

    @property
    def cells(self):
        return iter(self.nb.cells[1:])

    def cell_output(self, cell_index: int) -> List[Dict[str, Any]]:
        """Return a cell's outputs."""
        idx = cell_index + 1
        outputs = self.nb.cells[idx]["outputs"]
        return outputs

    def cell_output_html(self, cell_index: int) -> str:
        """Return a cell's HTML outputs concatenated into a string."""
        idx = cell_index + 1
        html = io.StringIO()
        for output in self.nb.cells[idx]["outputs"]:
            if output["output_type"] == "display_data":
                html.write(output["data"]["text/html"])
        return html.getvalue()

    def cell_output_text(self, cell_index: int) -> str:
        """Return a cell's text outputs concatenated into a string."""
        idx = cell_index + 1
        text = io.StringIO()
        # print(len(self.nb.cells), idx)
        for output in self.nb.cells[idx]["outputs"]:
            if output["output_type"] == "stream":
                text.write(output["text"])
        return text.getvalue()

    def all_output_text(self) -> str:
        text = io.StringIO()
        for i in range(len(self.nb["cells"]) - 1):
            text.write(self.cell_output_text(i))
        return text.getvalue()


@pytest.fixture
def run_id() -> str:
    """Fixture to return a fixed run id for testing."""
    return "lovely-dawn-32"


@pytest.fixture
def notebook(user, run_id, assets_path):
    """Fixture to load a notebook and work with it.

    This launches a live server,
    configures a notebook to use it, and enables
    devs to execute arbitrary cells.
    See test_notebooks.py for usage.
    """
    # wandb-related env vars:
    wandb_env = {k: v for k, v in os.environ.items() if k.startswith("WANDB")}

    # lovely-dawn-32 is run id we use for testing
    wandb_env["WANDB_RUN_ID"] = run_id

    @contextmanager
    def notebook_loader(
        nb_name: str,
        kernel_name: str = "wandb_python",
        notebook_type: PythonType = "jupyter",
        save_code: bool = True,
        **kwargs: Any,
    ):
        nb_path = assets_path(pathlib.Path("notebooks") / nb_name)
        shutil.copy(nb_path, os.path.join(os.getcwd(), os.path.basename(nb_path)))
        with open(nb_path) as f:
            nb = nbformat.read(f, as_version=4)

        # set up extra env vars and do monkey-patching.
        # in particular, we import and patch wandb.
        # this goes in the first cell of the notebook.

        setup_cell = io.StringIO()

        # env vars, particularly to point the sdk at the live test server (local_testcontainer):
        if not save_code:
            wandb_env["WANDB_SAVE_CODE"] = "false"
            wandb_env["WANDB_NOTEBOOK_NAME"] = ""
        else:
            wandb_env["WANDB_SAVE_CODE"] = "true"
            wandb_env["WANDB_NOTEBOOK_NAME"] = nb_name
        setup_cell.write("import os\n")
        for k, v in wandb_env.items():
            setup_cell.write(f"os.environ['{k}'] = '{v}'\n")
        # make wandb think we're in a specific type of notebook:
        setup_cell.write(
            "import pytest\n"
            "mp = pytest.MonkeyPatch()\n"
            "import wandb\n"
            f"mp.setattr(wandb.sdk.wandb_settings, '_get_python_type', lambda: '{notebook_type}')"
        )

        # inject:
        nb.cells.insert(0, nbformat.v4.new_code_cell(setup_cell.getvalue()))

        client = WandbNotebookClient(nb, kernel_name=kernel_name)
        try:
            with client.setup_kernel(**kwargs):
                yield client
        finally:
            pass
            # with open(os.path.join(os.getcwd(), "notebook.log"), "w") as f:
            #     f.write(client.all_output_text())
            # wandb.termlog("Find debug logs at: %s" % os.getcwd())
            # wandb.termlog(client.all_output_text())

    notebook_loader.base_url = wandb_env.get("WANDB_BASE_URL")

    return notebook_loader
