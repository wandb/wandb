from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import traceback
from base64 import b64encode
from typing import Any

import IPython
import IPython.display
import requests
from IPython.core.magic import Magics, line_cell_magic, magics_class
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
from requests.compat import urljoin

import wandb
import wandb.util
from wandb.sdk import wandb_setup
from wandb.sdk.lib import filesystem

logger = logging.getLogger(__name__)


def display_if_magic_is_used(run: wandb.Run) -> bool:
    """Display a run's page if the cell has the %%wandb cell magic.

    Args:
        run: The run to display.

    Returns:
        Whether the %%wandb cell magic was present.
    """
    if not _current_cell_wandb_magic:
        return False

    _current_cell_wandb_magic.display_if_allowed(run)
    return True


class _WandbCellMagicState:
    """State for a cell with the %%wandb cell magic."""

    def __init__(self, *, height: int) -> None:
        """Initializes the %%wandb cell magic state.

        Args:
            height: The desired height for displayed iframes.
        """
        self._height = height
        self._already_displayed = False

    def display_if_allowed(self, run: wandb.Run) -> None:
        """Display a run's iframe if one is not already displayed.

        Args:
            run: The run to display.
        """
        if self._already_displayed:
            return
        self._already_displayed = True

        _display_wandb_run(run, height=self._height)


_current_cell_wandb_magic: _WandbCellMagicState | None = None


def _display_by_wandb_path(path: str, *, height: int) -> None:
    """Display a wandb object (usually in an iframe) given its URI.

    Args:
        path: A path to a run, sweep, project, report, etc.
        height: Height of the iframe in pixels.
    """
    api = wandb.Api()

    try:
        obj = api.from_path(path)

        IPython.display.display_html(
            obj.to_html(height=height),
            raw=True,
        )
    except wandb.Error:
        traceback.print_exc()
        IPython.display.display_html(
            f"Path {path!r} does not refer to a W&B object you can access.",
            raw=True,
        )


def _display_wandb_run(run: wandb.Run, *, height: int) -> None:
    """Display a run (usually in an iframe).

    Args:
        run: The run to display.
        height: Height of the iframe in pixels.
    """
    IPython.display.display_html(
        run.to_html(height=height),
        raw=True,
    )


@magics_class
class WandBMagics(Magics):
    def __init__(self, shell):
        super().__init__(shell)

    @magic_arguments()
    @argument(
        "path",
        default=None,
        nargs="?",
        help="The path to a resource you want to display.",
    )
    @argument(
        "-h",
        "--height",
        default=420,
        type=int,
        help="The height of the iframe in pixels.",
    )
    @line_cell_magic
    def wandb(self, line: str, cell: str | None = None) -> None:
        """Display wandb resources in Jupyter.

        This can be used as a line magic:

            %wandb USERNAME/PROJECT/runs/RUN_ID

        Or as a cell magic:

            %%wandb -h 1024
            with wandb.init() as run:
                run.log({"loss": 1})
        """
        global _current_cell_wandb_magic

        args = parse_argstring(self.wandb, line)
        path: str | None = args.path
        height: int = args.height

        if path:
            _display_by_wandb_path(path, height=height)
            displayed = True
        elif run := wandb_setup.singleton().most_recent_active_run:
            _display_wandb_run(run, height=height)
            displayed = True
        else:
            displayed = False

        # If this is being used as a line magic ("%wandb"), we are done.
        # When used as a cell magic ("%%wandb"), we must run the cell.
        if cell is None:
            return

        if not displayed:
            _current_cell_wandb_magic = _WandbCellMagicState(height=height)

        try:
            IPython.get_ipython().run_cell(cell)
        finally:
            _current_cell_wandb_magic = None


def notebook_metadata_from_jupyter_servers_and_kernel_id():
    servers, kernel_id = jupyter_servers_and_kernel_id()
    for s in servers:
        if s.get("password"):
            raise ValueError("Can't query password protected kernel")
        res = requests.get(
            urljoin(s["url"], "api/sessions"), params={"token": s.get("token", "")}
        ).json()
        for nn in res:
            if isinstance(nn, dict) and nn.get("kernel") and "notebook" in nn:
                if nn["kernel"]["id"] == kernel_id:
                    return {
                        "root": s.get("root_dir", s.get("notebook_dir", os.getcwd())),
                        "path": nn["notebook"]["path"],
                        "name": nn["notebook"]["name"],
                    }

    if not kernel_id:
        return None

    # Built-in notebook server in VS Code
    try:
        from IPython import get_ipython

        ipython = get_ipython()
        notebook_path = ipython.kernel.shell.user_ns.get("__vsc_ipynb_file__")
        if notebook_path:
            return {
                "root": os.path.dirname(notebook_path),
                "path": notebook_path,
                "name": os.path.basename(notebook_path),
            }
    except Exception:
        return None


def notebook_metadata(silent: bool) -> dict[str, str]:
    """Attempt to query jupyter for the path and name of the notebook file.

    This can handle different jupyter environments, specifically:

    1. Colab
    2. Kaggle
    3. JupyterLab
    4. Notebooks
    5. Other?
    """
    error_message = (
        "Failed to detect the name of this notebook. You can set it manually"
        " with the WANDB_NOTEBOOK_NAME environment variable to enable code"
        " saving."
    )
    try:
        jupyter_metadata = notebook_metadata_from_jupyter_servers_and_kernel_id()

        # Colab:
        # request the most recent contents
        ipynb = attempt_colab_load_ipynb()
        if ipynb is not None and jupyter_metadata is not None:
            return {
                "root": "/content",
                "path": jupyter_metadata["path"],
                "name": jupyter_metadata["name"],
            }

        # Kaggle:
        if wandb.util._is_kaggle():
            # request the most recent contents
            ipynb = attempt_kaggle_load_ipynb()
            if ipynb:
                return {
                    "root": "/kaggle/working",
                    "path": ipynb["metadata"]["name"],
                    "name": ipynb["metadata"]["name"],
                }

        if jupyter_metadata:
            return jupyter_metadata
    except Exception:
        logger.exception(error_message)

    wandb.termerror(error_message)
    return {}


def jupyter_servers_and_kernel_id():
    """Return a list of servers and the current kernel_id.

    Used to query for the name of the notebook.
    """
    try:
        import ipykernel  # type: ignore

        kernel_id = re.search(
            "kernel-(.*).json", ipykernel.connect.get_connection_file()
        ).group(1)
        # We're either in jupyterlab or a notebook, lets prefer the newer jupyter_server package
        serverapp = wandb.util.get_module("jupyter_server.serverapp")
        notebookapp = wandb.util.get_module("notebook.notebookapp")
        servers = []
        if serverapp is not None:
            servers.extend(list(serverapp.list_running_servers()))
        if notebookapp is not None:
            servers.extend(list(notebookapp.list_running_servers()))
    except (AttributeError, ValueError, ImportError):
        return [], None

    return servers, kernel_id


def attempt_colab_load_ipynb():
    colab = wandb.util.get_module("google.colab")
    if colab:
        # This isn't thread safe, never call in a thread
        response = colab._message.blocking_request("get_ipynb", timeout_sec=5)
        if response:
            return response["ipynb"]


def attempt_kaggle_load_ipynb():
    kaggle = wandb.util.get_module("kaggle_session")
    if not kaggle:
        return None

    try:
        client = kaggle.UserSessionClient()
        parsed = json.loads(client.get_exportable_ipynb()["source"])
        # TODO: couldn't find a way to get the name of the notebook...
        parsed["metadata"]["name"] = "kaggle.ipynb"
    except Exception:
        wandb.termerror("Unable to load kaggle notebook.")
        logger.exception("Unable to load kaggle notebook.")
        return None

    return parsed


def attempt_colab_login(
    app_url: str,
    referrer: str | None = None,
):
    """This renders an iframe to wandb in the hopes it posts back an api key."""
    from google.colab import output  # type: ignore
    from google.colab._message import MessageError  # type: ignore
    from IPython import display

    display.display(
        display.Javascript(
            """
        window._wandbApiKey = new Promise((resolve, reject) => {{
            function loadScript(url) {{
            return new Promise(function(resolve, reject) {{
                let newScript = document.createElement("script");
                newScript.onerror = reject;
                newScript.onload = resolve;
                document.body.appendChild(newScript);
                newScript.src = url;
            }});
            }}
            loadScript("https://cdn.jsdelivr.net/npm/postmate/build/postmate.min.js").then(() => {{
            const iframe = document.createElement('iframe')
            iframe.style.cssText = "width:0;height:0;border:none"
            document.body.appendChild(iframe)
            const handshake = new Postmate({{
                container: iframe,
                url: '{}/authorize{}'
            }});
            const timeout = setTimeout(() => reject("Couldn't auto authenticate"), 5000)
            handshake.then(function(child) {{
                child.on('authorize', data => {{
                    clearTimeout(timeout)
                    resolve(data)
                }});
            }});
            }})
        }});
    """.format(
                app_url.replace("http:", "https:"),
                f"?ref={referrer}" if referrer else "",
            )
        )
    )
    try:
        return output.eval_js("_wandbApiKey")
    except MessageError:
        return None


class Notebook:
    def __init__(self, settings: wandb.Settings) -> None:
        self.outputs: dict[int, Any] = {}
        self.settings = settings
        self.shell = IPython.get_ipython()

    def save_display(self, exc_count, data_with_metadata):
        self.outputs[exc_count] = self.outputs.get(exc_count, [])

        # byte values such as images need to be encoded in base64
        # otherwise nbformat.v4.new_output will throw a NotebookValidationError
        data = data_with_metadata["data"]
        b64_data = {}
        for key in data:
            val = data[key]
            if isinstance(val, bytes):
                b64_data[key] = b64encode(val).decode("utf-8")
            else:
                b64_data[key] = val

        self.outputs[exc_count].append(
            {"data": b64_data, "metadata": data_with_metadata["metadata"]}
        )

    def probe_ipynb(self):
        """Return notebook as dict or None."""
        relpath = self.settings.x_jupyter_path
        if relpath:
            if os.path.exists(relpath):
                with open(relpath) as json_file:
                    data = json.load(json_file)
                    return data

        colab_ipynb = attempt_colab_load_ipynb()
        if colab_ipynb:
            return colab_ipynb

        kaggle_ipynb = attempt_kaggle_load_ipynb()
        if kaggle_ipynb and len(kaggle_ipynb["cells"]) > 0:
            return kaggle_ipynb

        return

    def save_ipynb(self) -> bool:
        if not self.settings.save_code:
            logger.info("not saving jupyter notebook")
            return False
        ret = False
        try:
            ret = self._save_ipynb()
        except Exception:
            wandb.termerror("Failed to save notebook.")
            logger.exception("Problem saving notebook.")
        return ret

    def _save_ipynb(self) -> bool:
        relpath = self.settings.x_jupyter_path
        logger.info("looking for notebook: %s", relpath)
        if relpath:
            if os.path.exists(relpath):
                shutil.copy(
                    relpath,
                    os.path.join(
                        self.settings._tmp_code_dir, os.path.basename(relpath)
                    ),
                )
                return True

        # TODO: likely only save if the code has changed
        colab_ipynb = attempt_colab_load_ipynb()
        if colab_ipynb:
            try:
                jupyter_metadata = (
                    notebook_metadata_from_jupyter_servers_and_kernel_id()
                )
                nb_name = jupyter_metadata["name"]
            except Exception:
                nb_name = "colab.ipynb"
            if not nb_name.endswith(".ipynb"):
                nb_name += ".ipynb"
            with open(
                os.path.join(
                    self.settings._tmp_code_dir,
                    nb_name,
                ),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(json.dumps(colab_ipynb))
            return True

        kaggle_ipynb = attempt_kaggle_load_ipynb()
        if kaggle_ipynb and len(kaggle_ipynb["cells"]) > 0:
            with open(
                os.path.join(
                    self.settings._tmp_code_dir, kaggle_ipynb["metadata"]["name"]
                ),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(json.dumps(kaggle_ipynb))
            return True

        return False

    def save_history(self, run: wandb.Run):
        """This saves all cell executions in the current session as a new notebook."""
        try:
            from nbformat import v4, validator, write  # type: ignore
        except ImportError:
            wandb.termerror(
                "The nbformat package was not found."
                " It is required to save notebook history."
            )
            return
        # TODO: some tests didn't patch ipython properly?
        if self.shell is None:
            return
        cells = []
        hist = list(self.shell.history_manager.get_range(output=True))
        if len(hist) <= 1 or not self.settings.save_code:
            logger.info("not saving jupyter history")
            return
        try:
            for _, execution_count, exc in hist:
                if exc[1]:
                    # TODO: capture stderr?
                    outputs = [
                        v4.new_output(output_type="stream", name="stdout", text=exc[1])
                    ]
                else:
                    outputs = []
                if self.outputs.get(execution_count):
                    for out in self.outputs[execution_count]:
                        outputs.append(
                            v4.new_output(
                                output_type="display_data",
                                data=out["data"],
                                metadata=out["metadata"] or {},
                            )
                        )
                cells.append(
                    v4.new_code_cell(
                        execution_count=execution_count, source=exc[0], outputs=outputs
                    )
                )
            if hasattr(self.shell, "kernel"):
                language_info = self.shell.kernel.language_info
            else:
                language_info = {"name": "python", "version": sys.version}
            logger.info("saving %i cells to _session_history.ipynb", len(cells))
            nb = v4.new_notebook(
                cells=cells,
                metadata={
                    "kernelspec": {
                        "display_name": f"Python {sys.version_info[0]}",
                        "name": f"python{sys.version_info[0]}",
                        "language": "python",
                    },
                    "language_info": language_info,
                },
            )
            state_path = os.path.join("code", "_session_history.ipynb")
            run._set_config_wandb("session_history", state_path)
            filesystem.mkdir_exists_ok(os.path.join(self.settings.files_dir, "code"))
            with open(
                os.path.join(self.settings._tmp_code_dir, "_session_history.ipynb"),
                "w",
                encoding="utf-8",
            ) as f:
                write(nb, f, version=4)
            with open(
                os.path.join(self.settings.files_dir, state_path),
                "w",
                encoding="utf-8",
            ) as f:
                write(nb, f, version=4)
        except (OSError, validator.NotebookValidationError):
            wandb.termerror("Unable to save notebook session history.")
            logger.exception("Unable to save notebook session history.")
