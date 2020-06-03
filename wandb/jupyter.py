import wandb
from wandb.apis import InternalApi, CommError
from wandb.run_manager import RunManager
from wandb import env
import time
import os
import threading
import logging
import uuid
from IPython.core.getipython import get_ipython
from IPython.core.magic import cell_magic, line_cell_magic, line_magic, Magics, magics_class
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
from IPython.display import display, Javascript
import requests
from requests.compat import urljoin
import re
import sys
from pkg_resources import resource_filename
from importlib import import_module

logger = logging.getLogger(__name__)


@magics_class
class WandBMagics(Magics):
    def __init__(self, shell, require_interaction=False):
        super(WandBMagics, self).__init__(shell)
        self.options = {}

    @magic_arguments()
    @argument(
        "-d", "--display", default=True,
        help="Display the wandb interface automatically"
    )
    @line_cell_magic
    def wandb(self, line, cell=None):
        # Record options
        args = parse_argstring(self.wandb, line)
        self.options["body"] = ""
        self.options['wandb_display'] = args.display

        # Register events
        display(Run())
        if cell is not None:
            get_ipython().run_cell(cell)


def attempt_colab_login(app_url):
    """This renders an iframe to wandb in the hopes it posts back an api key"""
    from google.colab import output
    from google.colab._message import MessageError
    from IPython import display

    display.display(display.Javascript('''
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
    ''' % app_url.replace("http:", "https:")))
    try:
        return output.eval_js('_wandbApiKey')
    except MessageError:
        return None


def notebook_metadata():
    """Attempts to query jupyter for the path and name of the notebook file"""
    error_message = "Failed to query for notebook name, you can set it manually with the WANDB_NOTEBOOK_NAME environment variable"
    try:
        import ipykernel
        from notebook.notebookapp import list_running_servers
        kernel_id = re.search('kernel-(.*).json', ipykernel.connect.get_connection_file()).group(1)
        servers = list(list_running_servers())  # TODO: sometimes there are invalid JSON files and this blows up
    except Exception:
        logger.error(error_message)
        return {}
    for s in servers:
        try:
            if s['password']:
                raise ValueError("Can't query password protected kernel")
            res = requests.get(urljoin(s['url'], 'api/sessions'), params={'token': s.get('token', '')}).json()
        except (requests.RequestException, ValueError):
            logger.error(error_message)
            return {}
        for nn in res:
            # TODO: wandb/client#400 found a case where res returned an array of strings...
            if isinstance(nn, dict) and nn.get("kernel") and 'notebook' in nn:
                if nn['kernel']['id'] == kernel_id:
                    return {"root": s['notebook_dir'], "path": nn['notebook']['path'], "name": nn['notebook']['name']}
    return {}


class JupyterAgent(object):
    """A class that only logs metrics after `wandb.log` has been called and stops logging at cell completion"""

    def __init__(self):
        self.paused = True
        self.outputs = {}
        self.shell = get_ipython()

    def start(self):
        if self.paused:
            self.paused = False
            self.rm = RunManager(wandb.run, output=False, cloud=wandb.run.mode != "dryrun")
            wandb.run.api._file_stream_api = None
            self.rm.mirror_stdout_stderr()
            # Init will return the last step of a resumed run
            # we update the runs history._steps in extreme hack fashion
            # TODO: this reserves a bigtime refactor
            new_step = self.rm.init_run(dict(os.environ))
            if new_step:
                wandb.run.history._steps = new_step + 1

    def stop(self):
        if not self.paused:
            self.save_history()
            self.rm.unmirror_stdout_stderr()
            wandb.run.close_files()
            self.rm.shutdown()
            self.paused = True

    def save_display(self, exc_count, data):
        self.outputs[exc_count] = self.outputs.get(exc_count, [])
        self.outputs[exc_count].append(data)

    def save_history(self):
        """This saves all cell executions in the current session as a new notebook"""
        try:
            from nbformat import write, v4, validator
        except ImportError:
            logger.error("Run pip install nbformat to save notebook history")
            return

        # TODO: some tests didn't patch ipython properly?
        if self.shell == None:
            return

        cells = []
        hist = list(self.shell.history_manager.get_range(output=True))
        if len(hist) <= 1 or not env.should_save_code():
            return

        try:
            for session, execution_count, exc in hist:
                if exc[1]:
                    # TODO: capture stderr?
                    outputs = [v4.new_output(output_type="stream", name="stdout", text=exc[1])]
                else:
                    outputs = []
                if self.outputs.get(execution_count):
                    for out in self.outputs[execution_count]:
                        outputs.append(v4.new_output(output_type="display_data", data=out["data"], metadata=out["metadata"] or {}))
                cells.append(v4.new_code_cell(
                    execution_count=execution_count,
                    source=exc[0],
                    outputs=outputs
                ))
            if hasattr(self.shell, "kernel"):
                language_info = self.shell.kernel.language_info
            else:
                language_info = {
                    'name': "python",
                    "version": sys.version
                }
            nb = v4.new_notebook(cells=cells, metadata={
                'kernelspec': {
                    'display_name': 'Python %i' % sys.version_info[0],
                    'name': 'python%i' % sys.version_info[0],
                    'language': 'python'
                },
                'language_info': language_info
            })
            state_path = os.path.join("code", "_session_history.ipynb")
            wandb.run.config._set_wandb("session_history", state_path)
            wandb.run.config.persist()
            wandb.util.mkdir_exists_ok(os.path.join(wandb.run.dir, "code"))
            with open(os.path.join(wandb.run.dir, state_path), 'w', encoding='utf-8') as f:
                write(nb, f, version=4)
        except (OSError, validator.NotebookValidationError) as e:
            logger.error("Unable to save ipython session history:\n%s", e)
            pass


class Run(object):
    def __init__(self, run=None):
        self.run = run or wandb.run

    def _repr_html_(self):
        state = "running"
        if self.run._jupyter_agent == None:
            state = "no_agent"
        elif self.run._jupyter_agent.paused:
            state = "paused"
        try:
            url = self.run.get_url(params={'jupyter': 'true', 'state': state})
            return '''<iframe src="%s" style="border:none;width:100%%;height:420px">
                </iframe>''' % url
        except CommError as e:
            return "Can't display wandb interface<br/>{}".format(e.message)
