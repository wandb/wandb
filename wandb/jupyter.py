from base64 import b64encode
import logging
import os
import re
import sys

import requests
from requests.compat import urljoin
import wandb

try:
    from IPython.core.getipython import get_ipython
    from IPython.core.magic import line_cell_magic, Magics, magics_class
    from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
    from IPython.display import display
except ImportError:
    wandb.termwarn("ipython is not supported in python 2.7, upgrade to 3.x")

    class Magics(object):
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


class Run(object):
    def __init__(self, run=None):
        self.run = run or wandb.run

    def _repr_html_(self):
        try:
            url = self.run._get_run_url() + "?jupyter=true"
            return (
                """<iframe src="%s" style="border:none;width:100%%;height:420px">
                </iframe>"""
                % url
            )
        except wandb.Error as e:
            return "Can't display wandb interface<br/>{}".format(e)


@magics_class
class WandBMagics(Magics):
    def __init__(self, shell, require_interaction=False):
        super(WandBMagics, self).__init__(shell)
        self.options = {}

    @magic_arguments()
    @argument(
        "-d",
        "--display",
        default=True,
        help="Display the wandb interface automatically",
    )
    @line_cell_magic
    def wandb(self, line, cell=None):
        # Record options
        args = parse_argstring(self.wandb, line)
        self.options["body"] = ""
        self.options["wandb_display"] = args.display
        # Register events
        display(Run())
        if cell is not None:
            get_ipython().run_cell(cell)


def notebook_metadata(silent):
    """Attempts to query jupyter for the path and name of the notebook file"""
    error_message = (
        "Failed to query for notebook name, you can set it manually with "
        "the WANDB_NOTEBOOK_NAME environment variable"
    )
    try:
        import ipykernel
        from notebook.notebookapp import list_running_servers

        kernel_id = re.search(
            "kernel-(.*).json", ipykernel.connect.get_connection_file()
        ).group(1)
        servers = list(
            list_running_servers()
        )  # TODO: sometimes there are invalid JSON files and this blows up
    except Exception:
        # TODO: Fix issue this is not the logger initialized in in wandb.init()
        # since logger is not attached, outputs to notebook
        if not silent:
            logger.error(error_message)
        return {}
    for s in servers:
        try:
            if s["password"]:
                raise ValueError("Can't query password protected kernel")
            res = requests.get(
                urljoin(s["url"], "api/sessions"), params={"token": s.get("token", "")}
            ).json()
        except (requests.RequestException, ValueError):
            if not silent:
                logger.error(error_message)
            return {}
        for nn in res:
            # TODO: wandb/client#400 found a case where res returned an array of
            # strings...
            if isinstance(nn, dict) and nn.get("kernel") and "notebook" in nn:
                if nn["kernel"]["id"] == kernel_id:
                    return {
                        "root": s["notebook_dir"],
                        "path": nn["notebook"]["path"],
                        "name": nn["notebook"]["name"],
                    }
    return {}


def attempt_colab_login(app_url):
    """This renders an iframe to wandb in the hopes it posts back an api key"""
    from google.colab import output
    from google.colab._message import MessageError
    from IPython import display

    display.display(
        display.Javascript(
            """
        window._wandbApiKey = new Promise((resolve, reject) => {
            function loadScript(url) {
            return new Promise(function(resolve, reject) {
                let newScript = document.createElement("script");
                newScript.onerror = reject;
                newScript.onload = resolve;
                document.body.appendChild(newScript);
                newScript.src = url;
            });
            }
            loadScript("https://cdn.jsdelivr.net/npm/postmate/build/postmate.min.js").then(() => {
            const iframe = document.createElement('iframe')
            iframe.style.cssText = "width:0;height:0;border:none"
            document.body.appendChild(iframe)
            const handshake = new Postmate({
                container: iframe,
                url: '%s/authorize'
            });
            const timeout = setTimeout(() => reject("Couldn't auto authenticate"), 5000)
            handshake.then(function(child) {
                child.on('authorize', data => {
                    clearTimeout(timeout)
                    resolve(data)
                });
            });
            })
        });
    """  # noqa: E501
            % app_url.replace("http:", "https:")
        )
    )
    try:
        return output.eval_js("_wandbApiKey")
    except MessageError:
        return None


class Notebook(object):
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

    def save_history(self):
        """This saves all cell executions in the current session as a new notebook"""
        try:
            from nbformat import write, v4, validator
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
            wandb.run.config["_wandb"]["session_history"] = state_path
            wandb.run.config.persist()
            wandb.util.mkdir_exists_ok(os.path.join(wandb.run.dir, "code"))
            with open(
                os.path.join(wandb.run.dir, state_path), "w", encoding="utf-8"
            ) as f:
                write(nb, f, version=4)
        except (OSError, validator.NotebookValidationError) as e:
            logger.error("Unable to save ipython session history:\n%s", e)
            pass
