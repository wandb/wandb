import io
import os
import pathlib
import re
import shutil
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock

import filelock
import IPython
import IPython.display
import nbformat
import pytest
import wandb
import wandb.util
from nbclient import NotebookClient
from nbclient.client import CellExecutionError
from typing_extensions import Any, Generator, override
from wandb.sdk.lib import ipython

_NOTEBOOK_LOCKFILE = os.path.join(
    os.path.dirname(__file__),
    ".test_notebooks.lock",
)


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
def mocked_ipython(monkeypatch):
    monkeypatch.setattr(ipython, "in_jupyter", lambda: True)

    def run_cell(cell):
        print("Running cell: ", cell)
        exec(cell)

    mock_get_ipython_result = MagicMock()
    mock_get_ipython_result.run_cell = run_cell
    mock_get_ipython_result.html = MagicMock()
    mock_get_ipython_result.kernel.shell.user_ns = {}

    monkeypatch.setattr(IPython, "get_ipython", lambda: mock_get_ipython_result)
    monkeypatch.setattr(
        IPython.display,
        "display",
        lambda obj, **kwargs: mock_get_ipython_result.html(obj._repr_html_()),
    )

    return mock_get_ipython_result


class WandbNotebookClient(NotebookClient):
    def execute_all(self, store_history: bool = True) -> None:
        """Execute all cells in order."""
        for idx, cell in enumerate(self.nb.cells):
            try:
                super().execute_cell(
                    cell=cell,
                    cell_index=idx,
                    store_history=False if idx == 0 else store_history,
                )
            except CellExecutionError as e:
                if sys.stderr.isatty():
                    raise
                else:
                    # Strip ANSI sequences in non-TTY environments,
                    # particularly in CI.
                    raise CellExecutionError(
                        _strip_ansi(e.traceback),
                        e.ename,
                        e.evalue,
                    ) from None

    @property
    def cells(self):
        return iter(self.nb.cells[1:])

    def cell_output(self, cell_index: int) -> list[dict[str, Any]]:
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

    @override
    @contextmanager
    def setup_kernel(self, **kwargs: Any) -> Generator[None, None, None]:
        # Work around https://github.com/jupyter/jupyter_client/issues/487
        # by preventing multiple processes from starting up a Jupyter kernel
        # at the same time.
        open_client_lock = filelock.FileLock(_NOTEBOOK_LOCKFILE)
        open_client_lock.acquire()
        unlocked = False

        try:
            with super().setup_kernel(**kwargs):
                open_client_lock.release()
                unlocked = True
                yield
        finally:
            if not unlocked:
                open_client_lock.release()


@pytest.fixture
def run_id() -> str:
    """A fixed run ID for testing."""
    return "lovely-dawn-32"


@pytest.fixture
def notebook(user, run_id, assets_path):
    """A context manager to run a notebook.

    The context manager returns a WandbNotebookClient that can be used to
    execute cells and retrieve their output.

    Args:
        nb_name: The notebook file to load from the assets directory.
        kernel_name: The kernel to use to run the notebook.
        notebook_type: Whether to configure wandb to treat this as a Jupyter
            (web) or iPython (console) notebook.
        save_code: Whether to enable wandb code saving in the setup cell.
        skip_api_key_env: Whether to pretend that no API key is set to cause
            wandb to attempt to log in.
    """
    _ = user  # Run all notebooks with a fake logged-in user.

    @contextmanager
    def notebook_loader(
        nb_name: str,
        kernel_name: str = "wandb_python",
        notebook_type: ipython.PythonType = "jupyter",
        save_code: bool = True,
        skip_api_key_env: bool = False,
    ):
        # Copy the notebook to the current directory for code-saving to work.
        #
        # This relies on another auto-use fixture to point CWD at a temporary
        # path.
        nb_path = assets_path(pathlib.Path("notebooks", nb_name))
        shutil.copy(nb_path, nb_name)

        # Read the notebook.
        with open(nb_path) as f:
            nb_node: nbformat.NotebookNode = nbformat.read(f, as_version=4)

        wandb_env = {k: v for k, v in os.environ.items() if k.startswith("WANDB")}
        wandb_env["WANDB_RUN_ID"] = run_id
        if save_code:
            wandb_env["WANDB_SAVE_CODE"] = "true"
            wandb_env["WANDB_NOTEBOOK_NAME"] = nb_name
        else:
            wandb_env["WANDB_SAVE_CODE"] = "false"
            wandb_env["WANDB_NOTEBOOK_NAME"] = ""

        setup_cell = io.StringIO()

        # Forward any WANDB environment variables to the notebook.
        setup_cell.write("import os\n")
        for k, v in wandb_env.items():
            if skip_api_key_env and k == "WANDB_API_KEY":
                continue

            setup_cell.write(f"os.environ['{k}'] = '{v}'\n")

        # Make wandb think we're in a specific type of notebook.
        setup_cell.write(
            "from wandb.sdk.lib import ipython\n"
            f"ipython._get_python_type = lambda: '{notebook_type}'\n",
        )

        nb_node.cells.insert(0, nbformat.v4.new_code_cell(setup_cell.getvalue()))

        client = WandbNotebookClient(nb_node, kernel_name=kernel_name)
        with client.setup_kernel():
            yield client

    return notebook_loader


_ANSI_RE = re.compile(r"\033\[[;?0-9]*[a-zA-Z]")


def _strip_ansi(value: str) -> str:
    """Remove ANSI escape sequences from the string."""
    return _ANSI_RE.sub("", value)
