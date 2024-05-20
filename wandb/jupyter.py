import json
import logging
import os
import re
import shutil
import sys
from base64 import b64encode
from typing import Dict

import requests
from requests.compat import urljoin

import wandb
import wandb.util
from wandb.sdk.lib import filesystem

try:
    from IPython.core.getipython import get_ipython
    from IPython.core.magic import Magics, line_cell_magic, magics_class
    from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
    from IPython.display import display
except ImportError:
    wandb.termwarn("ipython is not supported in python 2.7, upgrade to 3.x")

    class Magics:
        pass

    def magics_class(*args, **kwargs):
        return lambda *args, **kwargs: None

    def magic_arguments(*args, **kwargs):
        return lambda *args, **kwargs: None

    def argument(*args, **kwargs):
        return lambda *args, **kwargs: None

    def line_cell_magic(*args, **kwargs):
        return lambda *args, **kwargs: None


logger = logging.getLogger(__name__)

__IFrame = None


def maybe_display():
    """Display a run if the user added cell magic and we have run."""
    if __IFrame is not None:
        return __IFrame.maybe_display()
    return False


def quiet():
    if __IFrame is not None:
        return __IFrame.opts.get("quiet")
    return False


class IFrame:
    def __init__(self, path=None, opts=None):
        self.path = path
        self.api = wandb.Api()
        self.opts = opts or {}
        self.displayed = False
        self.height = self.opts.get("height", 420)

    def maybe_display(self) -> bool:
        if not self.displayed and (self.path or wandb.run):
            display(self)
        return self.displayed

    def _repr_html_(self):
        try:
            self.displayed = True
            if self.opts.get("workspace", False):
                if self.path is None and wandb.run:
                    self.path = wandb.run.path
            if isinstance(self.path, str):
                object = self.api.from_path(self.path)
            else:
                object = wandb.run
            if object is None:
                if wandb.Api().api_key is None:
                    return "You must be logged in to render wandb in jupyter, run `wandb.login()`"
                else:
                    object = self.api.project(
                        "/".join(
                            [
                                wandb.Api().default_entity,
                                wandb.util.auto_project_name(None),
                            ]
                        )
                    )
            return object.to_html(self.height, hidden=False)
        except wandb.Error as e:
            return f"Can't display wandb interface<br/>{e}"


@magics_class
class WandBMagics(Magics):
    def __init__(self, shell, require_interaction=False):
        super().__init__(shell)
        self.options = {}

    @magic_arguments()
    @argument(
        "path",
        default=None,
        nargs="?",
        help="A path to a resource you want to display, defaults to wandb.run.path",
    )
    @argument(
        "-w",
        "--workspace",
        default=False,
        action="store_true",
        help="Display the entire run project workspace",
    )
    @argument(
        "-q",
        "--quiet",
        default=False,
        action="store_true",
        help="Display the minimal amount of output",
    )
    @argument(
        "-h",
        "--height",
        default=420,
        type=int,
        help="The height of the iframe in pixels",
    )
    @line_cell_magic
    def wandb(self, line, cell=None):
        """Display wandb resources in jupyter.  This can be used as cell or line magic.

        %wandb USERNAME/PROJECT/runs/RUN_ID
        ---
        %%wandb -h 1024
        with wandb.init() as run:
            run.log({"loss": 1})
        """
        # Record options
        args = parse_argstring(self.wandb, line)
        self.options["height"] = args.height
        self.options["workspace"] = args.workspace
        self.options["quiet"] = args.quiet
        iframe = IFrame(args.path, opts=self.options)
        displayed = iframe.maybe_display()
        if cell is not None:
            if not displayed:
                # Store the IFrame globally and attempt to display if we have a run
                cell = (
                    f"wandb.jupyter.__IFrame = wandb.jupyter.IFrame(opts={self.options})\n"
                    + cell
                    + "\nwandb.jupyter.__IFrame = None"
                )
            get_ipython().run_cell(cell)


def notebook_metadata_from_jupyter_servers_and_kernel_id():
    servers, kernel_id = jupyter_servers_and_kernel_id()
    for s in servers:
        if s.get("password"):
            raise ValueError("Can't query password protected kernel")
        res = requests.get(
            urljoin(s["url"], "api/sessions"), params={"token": s.get("token", "")}
        ).json()
        for nn in res:
            # TODO: wandb/client#400 found a case where res returned an array of
            # strings...
            if isinstance(nn, dict) and nn.get("kernel") and "notebook" in nn:
                if nn["kernel"]["id"] == kernel_id:
                    return {
                        "root": s.get("root_dir", s.get("notebook_dir", os.getcwd())),
                        "path": nn["notebook"]["path"],
                        "name": nn["notebook"]["name"],
                    }
    return None


def notebook_metadata(silent: bool) -> Dict[str, str]:
    """Attempt to query jupyter for the path and name of the notebook file.

    This can handle different jupyter environments, specifically:

    1. Colab
    2. Kaggle
    3. JupyterLab
    4. Notebooks
    5. Other?
    """
    error_message = (
        "Failed to detect the name of this notebook, you can set it manually with "
        "the WANDB_NOTEBOOK_NAME environment variable to enable code saving."
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
        if not silent:
            logger.error(error_message)
        return {}
    except Exception:
        # TODO: report this exception
        # TODO: Fix issue this is not the logger initialized in in wandb.init()
        # since logger is not attached, outputs to notebook
        if not silent:
            logger.error(error_message)
        return {}


def jupyter_servers_and_kernel_id():
    """Return a list of servers and the current kernel_id.

    Used to query for the name of the notebook.
    """
    try:
        import ipykernel

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
        return servers, kernel_id
    except (AttributeError, ValueError, ImportError):
        return [], None


def attempt_colab_load_ipynb():
    colab = wandb.util.get_module("google.colab")
    if colab:
        # This isn't thread safe, never call in a thread
        response = colab._message.blocking_request("get_ipynb", timeout_sec=5)
        if response:
            return response["ipynb"]


def attempt_kaggle_load_ipynb():
    kaggle = wandb.util.get_module("kaggle_session")
    if kaggle:
        try:
            client = kaggle.UserSessionClient()
            parsed = json.loads(client.get_exportable_ipynb()["source"])
            # TODO: couldn't find a way to get the name of the notebook...
            parsed["metadata"]["name"] = "kaggle.ipynb"
            return parsed
        except Exception:
            logger.exception("Unable to load kaggle notebook")
            return None


def attempt_colab_login(app_url):
    """This renders an iframe to wandb in the hopes it posts back an api key."""
    from google.colab import output
    from google.colab._message import MessageError
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
                url: '{}/authorize'
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
    """.format(app_url.replace("http:", "https:"))
        )
    )
    try:
        return output.eval_js("_wandbApiKey")
    except MessageError:
        return None


class Notebook:
    def __init__(self, settings):
        self.outputs = {}
        self.settings = settings
        self.shell = get_ipython()

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
        relpath = self.settings._jupyter_path
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
        except Exception as e:
            logger.info(f"Problem saving notebook: {repr(e)}")
        return ret

    def _save_ipynb(self) -> bool:
        relpath = self.settings._jupyter_path
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

    def save_history(self):
        """This saves all cell executions in the current session as a new notebook."""
        try:
            from nbformat import v4, validator, write
        except ImportError:
            logger.error("Run pip install nbformat to save notebook history")
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
                        "display_name": "Python %i" % sys.version_info[0],
                        "name": "python%i" % sys.version_info[0],
                        "language": "python",
                    },
                    "language_info": language_info,
                },
            )
            state_path = os.path.join("code", "_session_history.ipynb")
            wandb.run._set_config_wandb("session_history", state_path)
            filesystem.mkdir_exists_ok(os.path.join(wandb.run.dir, "code"))
            with open(
                os.path.join(self.settings._tmp_code_dir, "_session_history.ipynb"),
                "w",
                encoding="utf-8",
            ) as f:
                write(nb, f, version=4)
            with open(
                os.path.join(wandb.run.dir, state_path), "w", encoding="utf-8"
            ) as f:
                write(nb, f, version=4)
        except (OSError, validator.NotebookValidationError) as e:
            logger.error("Unable to save ipython session history:\n%s", e)
            pass
