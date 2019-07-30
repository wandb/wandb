# -*- coding: utf-8 -*-

# Three possible modes:
#     'cli': running from "wandb" command
#     'run': we're a script launched by "wandb run"
#     'dryrun': we're a script not launched by "wandb run"

from __future__ import absolute_import, print_function

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.8.6'

import atexit
import click
import io
import json
import logging
import time
import os
import contextlib
import signal
import six
import getpass
import socket
import subprocess
import sys
import traceback
import tempfile
import re
import glob
from importlib import import_module

from . import env
from . import io_wrap
from .core import *

# These imports need to be below "from .core import *" until we remove
# 'from wandb import __stage_dir__' from api.py etc.
from wandb.apis import InternalApi, PublicApi, CommError
from wandb import wandb_types as types
from wandb import wandb_config
from wandb import wandb_run
from wandb import wandb_socket
from wandb import streaming_log
from wandb import util
from wandb.run_manager import LaunchError
from wandb.data_types import Image
from wandb.data_types import Audio
from wandb.data_types import Table
from wandb.data_types import Html
from wandb.data_types import Object3D
from wandb.data_types import Histogram
from wandb.data_types import Graph
from wandb import trigger
from wandb.dataframes import image_categorizer_dataframe
from wandb.dataframes import image_segmentation_dataframe
from wandb.dataframes import image_segmentation_binary_dataframe
from wandb.dataframes import image_segmentation_multiclass_dataframe

from wandb import wandb_torch


logger = logging.getLogger(__name__)


# this global W&B debug log gets re-written by every W&B process
if __stage_dir__ is not None:
    GLOBAL_LOG_FNAME = os.path.abspath(os.path.join(wandb_dir(), 'debug.log'))
else:
    GLOBAL_LOG_FNAME = os.path.join(tempfile.gettempdir(), 'wandb-debug.log')

def _debugger(*args):
    import pdb
    pdb.set_trace()


class Callbacks():
    @property
    def Keras(self):
        termlog(
            "DEPRECATED: wandb.callbacks is deprecated, use `from wandb.keras import WandbCallback`")
        from wandb.keras import WandbCallback
        return WandbCallback


callbacks = Callbacks()


def hook_torch(*args, **kwargs):
    termlog(
        "DEPRECATED: wandb.hook_torch is deprecated, use `wandb.watch`")
    return watch(*args, **kwargs)


watch_called = False


def watch(models, criterion=None, log="gradients", log_freq=100):
    """
    Hooks into the torch model to collect gradients and the topology.  Should be extended
    to accept arbitrary ML models.

    :param (torch.Module) models: The model to hook, can be a tuple
    :param (torch.F) criterion: An optional loss value being optimized
    :param (str) log: One of "gradients", "parameters", "all", or None
    :param (int) log_freq: log gradients and parameters every N batches
    :return: (wandb.Graph) The graph object that will populate after the first backward pass
    """
    global watch_called
    if run is None:
        raise ValueError(
            "You must call `wandb.init` before calling watch")
    if watch_called:
        raise ValueError(
            "You can only call `wandb.watch` once per process. If you want to watch multiple models, pass them in as a tuple."
        )
    watch_called = True
    log_parameters = False
    log_gradients = True
    if log == "all":
        log_parameters = True
    elif log == "parameters":
        log_parameters = True
        log_gradients = False
    elif log is None:
        log_gradients = False

    if not isinstance(models, (tuple, list)):
        models = (models,)
    graphs = []
    prefix = ''
    for idx, model in enumerate(models):
        if idx > 0:
            prefix = "graph_%i" % idx

        run.history.torch.add_log_hooks_to_pytorch_module(
            model, log_parameters=log_parameters, log_gradients=log_gradients, prefix=prefix, log_freq=log_freq)

        graph = wandb_torch.TorchGraph.hook_torch(
            model, criterion, graph_idx=idx)
        graphs.append(graph)
        # NOTE: the graph is set in run.summary by hook_torch on the backward pass
    return graphs


class ExitHooks(object):
    def __init__(self):
        self.exit_code = 0
        self.exception = None

    def hook(self):
        self._orig_exit = sys.exit
        sys.exit = self.exit
        sys.excepthook = self.exc_handler

    def exit(self, code=0):
        orig_code = code
        if code is None:
            code = 0
        elif not isinstance(code, int):
            code = 1
        self.exit_code = code
        self._orig_exit(orig_code)

    def was_ctrl_c(self):
        return isinstance(self.exception, KeyboardInterrupt)

    def exc_handler(self, exc_type, exc, *tb):
        self.exit_code = 1
        self.exception = exc
        if issubclass(exc_type, Error):
            termerror(str(exc))

        if self.was_ctrl_c():
            self.exit_code = 255

        traceback.print_exception(exc_type, exc, *tb)


def _init_headless(run, cloud=True):
    global join
    global _user_process_finished_called

    environ = dict(os.environ)
    run.set_environment(environ)

    server = wandb_socket.Server()
    run.socket = server
    hooks = ExitHooks()
    hooks.hook()

    if sys.platform == "win32":
        # PTYs don't work in windows so we use pipes.
        stdout_master_fd, stdout_slave_fd = os.pipe()
        stderr_master_fd, stderr_slave_fd = os.pipe()
    else:
        stdout_master_fd, stdout_slave_fd = io_wrap.wandb_pty(resize=False)
        stderr_master_fd, stderr_slave_fd = io_wrap.wandb_pty(resize=False)

    headless_args = {
        'command': 'headless',
        'pid': os.getpid(),
        'stdout_master_fd': stdout_master_fd,
        'stderr_master_fd': stderr_master_fd,
        'cloud': cloud,
        'port': server.port
    }
    internal_cli_path = os.path.join(
        os.path.dirname(__file__), 'internal_cli.py')

    if six.PY2:
        # TODO(adrian): close_fds=False is bad for security. we set
        # it so we can pass the PTY FDs to the wandb process. We
        # should use subprocess32, which has pass_fds.
        popen_kwargs = {'close_fds': False}
    else:
        popen_kwargs = {'pass_fds': [stdout_master_fd, stderr_master_fd]}

    # TODO(adrian): ensure we use *exactly* the same python interpreter
    # TODO(adrian): make wandb the foreground process so we don't give
    # up terminal control until syncing is finished.
    # https://stackoverflow.com/questions/30476971/is-the-child-process-in-foreground-or-background-on-fork-in-c
    wandb_process = subprocess.Popen([sys.executable, internal_cli_path, json.dumps(
        headless_args)], env=environ, **popen_kwargs)
    termlog('Started W&B process version {} with PID {}'.format(
        __version__, wandb_process.pid))
    os.close(stdout_master_fd)
    os.close(stderr_master_fd)
    # Listen on the socket waiting for the wandb process to be ready
    try:
        success, message = server.listen(30)
    except KeyboardInterrupt:
        success = False
    else:
        if not success:
            termerror('W&B process (PID {}) did not respond'.format(
                wandb_process.pid))
    if not success:
        wandb_process.kill()
        for i in range(20):
            time.sleep(0.1)
            if wandb_process.poll() is not None:
                break
        if wandb_process.poll() is None:
            termerror('Failed to kill wandb process, PID {}'.format(
                wandb_process.pid))
        # TODO attempt to upload a debug log
        path = GLOBAL_LOG_FNAME.replace(os.getcwd()+os.sep, "")
        raise LaunchError(
            "W&B process failed to launch, see: {}".format(path))

    stdout_slave = os.fdopen(stdout_slave_fd, 'wb')
    stderr_slave = os.fdopen(stderr_slave_fd, 'wb')

    stdout_redirector = io_wrap.FileRedirector(sys.stdout, stdout_slave)
    stderr_redirector = io_wrap.FileRedirector(sys.stderr, stderr_slave)

    # TODO(adrian): we should register this right after starting the wandb process to
    # make sure we shut down the W&B process eg. if there's an exception in the code
    # above
    atexit.register(_user_process_finished, server, hooks,
                    wandb_process, stdout_redirector, stderr_redirector)

    def _wandb_join():
        _user_process_finished(server, hooks,
                               wandb_process, stdout_redirector, stderr_redirector)
    join = _wandb_join
    _user_process_finished_called = False

    # redirect output last of all so we don't miss out on error messages
    stdout_redirector.redirect()
    if not env.is_debug():
        stderr_redirector.redirect()


def load_ipython_extension(ipython):
    pass

def jupyter_login(force=True):
    """Attempt to login from a jupyter environment

    If force=False, we'll only attempt to auto-login, otherwise we'll prompt the user
    """
    key = None
    if 'google.colab' in sys.modules:
        key = jupyter.attempt_colab_login(run.api.app_url)
        if key:
            os.environ[env.API_KEY] = key
            util.write_netrc(run.api.api_url, "user", key)
    if not key and force:
        termerror(
            "Not authenticated.  Copy a key from https://app.wandb.ai/authorize")
        key = getpass.getpass("API Key: ").strip()
        if len(key) == 40:
            os.environ[env.API_KEY] = key
            util.write_netrc(run.api.api_url, "user", key)
        else:
            raise ValueError("API Key must be 40 characters long")
    return key


def _init_jupyter(run):
    """Asks for user input to configure the machine if it isn't already and creates a new run.
    Log pushing and system stats don't start until `wandb.log()` is first called.
    """
    from wandb import jupyter
    from IPython.core.display import display, HTML
    # TODO: Should we log to jupyter?
    # global logging had to be disabled because it set the level to debug
    # I also disabled run logging because we're rairly using it.
    # try_to_set_up_global_logging()
    # run.enable_logging()

    if not run.api.api_key:
        jupyter_login()
        # Ensure our api client picks up the new key
        run.api.reauth()
    os.environ["WANDB_JUPYTER"] = "true"
    run.resume = "allow"
    display(HTML('''
        Notebook configured with <a href="https://wandb.com" target="_blank">W&B</a>. You can <a href="{}" target="_blank">open</a> the run page, or call <code>%%wandb</code>
        in a cell containing your training loop to display live results.  Learn more in our <a href="https://docs.wandb.com/docs/integrations/jupyter.html" target="_blank">docs</a>.
    '''.format(run.get_url())))
    try:
        run.save()
    except (CommError, ValueError) as e:
        termerror(str(e))
    run.set_environment()
    run._init_jupyter_agent()
    ipython = get_ipython()
    ipython.register_magics(jupyter.WandBMagics)

    def reset_start():
        """Reset START_TIME to when the cell starts"""
        global START_TIME
        START_TIME = time.time()
    ipython.events.register("pre_run_cell", reset_start)
    ipython.events.register('post_run_cell', run._stop_jupyter_agent)


join = None
_user_process_finished_called = False


def _user_process_finished(server, hooks, wandb_process, stdout_redirector, stderr_redirector):
    global _user_process_finished_called
    if _user_process_finished_called:
        return
    _user_process_finished_called = True
    trigger.call('on_finished')

    stdout_redirector.restore()
    if not env.is_debug():
        stderr_redirector.restore()

    termlog()
    termlog("Waiting for W&B process to finish, PID {}".format(wandb_process.pid))
    server.done(hooks.exit_code)
    try:
        while wandb_process.poll() is None:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    if wandb_process.poll() is None:
        termlog('Killing W&B process, PID {}'.format(wandb_process.pid))
        wandb_process.kill()


# Will be set to the run object for the current run, as returned by
# wandb.init(). We may want to get rid of this, but WandbCallback
# relies on it, and it improves the API a bit (user doesn't have to
# pass the run into WandbCallback)
run = None
config = None  # config object shared with the global run
summary = None  # summary object shared with the global run
Api = PublicApi
# Stores what modules have been patched
patched = {
    "tensorboard": [],
    "keras": []
}
_saved_files = set()


def save(glob_str, base_path=None, policy="live"):
    """ Ensure all files matching *glob_str* are synced to wandb with the policy specified.

    base_path: the base path to run the glob relative to
    policy:
        live: upload the file as it changes, overwriting the previous version
        end: only upload file when the run ends
    """
    global _saved_files
    if run is None:
        raise ValueError(
            "You must call `wandb.init` before calling save")
    if policy not in ("live", "end"):
        raise ValueError(
            'Only "live" and "end" policies are currently supported.')
    if base_path is None:
        base_path = os.path.dirname(glob_str)
    if isinstance(glob_str, bytes):
        glob_str = glob_str.decode('utf-8')
    wandb_glob_str = os.path.relpath(glob_str, base_path)
    if "../" in wandb_glob_str:
        raise ValueError(
            "globs can't walk above base_path")
    if (glob_str, base_path, policy) in _saved_files:
        return []
    if glob_str.startswith("gs://") or glob_str.startswith("s3://"):
        termlog(
            "%s is a cloud storage url, can't save file to wandb." % glob_str)
        return []
    run.send_message(
        {"save_policy": {"glob": wandb_glob_str, "policy": policy}})
    files = []
    for path in glob.glob(glob_str):
        file_name = os.path.relpath(path, base_path)
        abs_path = os.path.abspath(path)
        wandb_path = os.path.join(run.dir, file_name)
        util.mkdir_exists_ok(os.path.dirname(wandb_path))
        # We overwrite existing symlinks because namespaces can change in Tensorboard
        if os.path.islink(wandb_path) and abs_path != os.readlink(wandb_path):
            os.remove(wandb_path)
            os.symlink(abs_path, wandb_path)
        elif not os.path.exists(wandb_path):
            os.symlink(abs_path, wandb_path)
        files.append(wandb_path)
    _saved_files.add((glob_str, base_path, policy))
    return files


def restore(name, run_path=None, replace=False, root="."):
    """ Downloads the specified file from cloud storage into the current run directory
    if it doesn exist.

    name: the name of the file
    run_path: optional path to a different run to pull files from
    replace: whether to download the file even if it already exists locally
    root: the directory to download the file to.  Defaults to the current
        directory or the run directory if wandb.init was called.

    returns None if it can't find the file, otherwise a file object open for reading
    raises wandb.CommError if it can't find the run
    """
    if run_path is None and run is None:
        raise ValueError(
            "You must call `wandb.init` before calling restore or specify a run_path")
    api = Api()
    api_run = api.run(run_path or run.path)
    root = run.dir if run else root
    path = os.path.exists(os.path.join(root, name))
    if path and replace == False:
        return open(path, "r")
    files = api_run.files([name])
    if len(files) == 0:
        return None
    return files[0].download(root=root, replace=True)

_tunnel_process = None
def tunnel(host, port):
    """Simple helper to open a tunnel.  Returns a public HTTPS url or None"""
    global _tunnel_process
    if _tunnel_process:
        _tunnel_process.kill()
        _tunnel_process = None
    process = subprocess.Popen("ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -R 80:{}:{} serveo.net".format(host, port), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while process.returncode is None:
        for line in process.stdout:
            match = re.match(r".+(https.+)$", line.decode("utf-8").strip())
            if match:
                _tunnel_process = process
                return match.group(1)
        # set returncode if the process has exited
        process.poll()
        time.sleep(1)
    return None

def monitor(options={}):
    """Starts syncing with W&B if you're in Jupyter.  Displays your W&B charts live in a Jupyter notebook.
    It's currently a context manager for legacy reasons.
    """
    try:
        from IPython.display import display
    except ImportError:
        def display(stuff): return None

    class Monitor():
        def __init__(self, options={}):
            if os.getenv("WANDB_JUPYTER"):
                display(jupyter.Run())
            else:
                self.rm = False
                termerror(
                    "wandb.monitor is only functional in Jupyter notebooks")

        def __enter__(self):
            termlog(
                "DEPRECATED: with wandb.monitor(): is deprecated, add %%wandb to the beginning of a cell to see live results.")
            pass

        def __exit__(self, *args):
            pass

    return Monitor(options)


def log(row=None, commit=True, step=None, *args, **kwargs):
    """Log a dict to the global run's history.

    wandb.log({'train-loss': 0.5, 'accuracy': 0.9})

    Args:
        row (dict, optional): A dict of serializable python objects i.e str: ints, floats, Tensors, dicts, or wandb.data_types
        commit (boolean, optional): Persist a set of metrics, if false just update the existing dict
        step (integer, optional): The global step in processing. This sets commit=True any time step increases
    """

    if run is None:
        raise ValueError(
            "You must call `wandb.init` in the same process before calling log")

    tensorboard_patched = len(patched["tensorboard"]) > 0

    if tensorboard_patched and step is None:
        termwarn(
            "wandb.log called without a step keyword argument.  Pass the same step that tensorboard is using to avoid data loss see:\nhttps://docs.wandb.com/docs/integrations/tensorboard.html#custom-metrics", repeat=False)

    if row is None:
        row = {}

    if any(not isinstance(key, six.string_types) for key in row.keys()):
        raise ValueError("Key values passed to `wandb.log` must be strings.")

    if commit or step is not None:
        run.history.add(row, *args, step=step, **kwargs)
    else:
        run.history.update(row, *args, **kwargs)


def ensure_configured():
    global GLOBAL_LOG_FNAME, api
    # We re-initialize here for tests
    api = InternalApi()
    GLOBAL_LOG_FNAME = os.path.abspath(os.path.join(wandb_dir(), 'debug.log'))

def uninit():
    """Undo the effects of init(). Useful for testing.
    """
    global run, config, summary, watch_called, patched, _saved_files
    run = config = summary = None
    watch_called = False
    # UNDO patches
    for mod in patched["tensorboard"]:
        module = import_module(mod[0])
        parts = mod[1].split(".")
        if len(parts) > 1:
            module = getattr(module, parts[0])
            mod[1] = parts[1]
        setattr(module, mod[1], getattr(module, "orig_"+mod[1]))
    patched["tensorboard"] = []
    _saved_files = set()


def reset_env(exclude=[]):
    """Remove environment variables, used in Jupyter notebooks"""
    if os.getenv(env.INITED):
        wandb_keys = [key for key in os.environ.keys() if key.startswith(
            'WANDB_') and key not in exclude]
        for key in wandb_keys:
            del os.environ[key]
        return True
    else:
        return False


def try_to_set_up_global_logging():
    """Try to set up global W&B debug log that gets re-written by every W&B process.

    It may fail (and return False) eg. if the current directory isn't user-writable
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d [%(filename)s:%(funcName)s():%(lineno)s] %(message)s')

    if env.is_debug():
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)

        root.addHandler(handler)

    try:
        handler = logging.FileHandler(GLOBAL_LOG_FNAME, mode='w')
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)

        root.addHandler(handler)
    except IOError as e:  # eg. in case wandb directory isn't writable
        termerror('Failed to set up logging: {}'.format(e))
        return False

    return True


def _get_python_type():
    try:
        if 'terminal' in get_ipython().__module__:
            return 'ipython'
        else:
            return 'jupyter'
    except (NameError, AttributeError):
        return "python"


def sagemaker_auth(overrides={}, path="."):
    """ Write a secrets.env file with the W&B ApiKey and any additional secrets passed.

        Args:
            overrides (dict, optional): Additional environment variables to write to secrets.env
            path (str, optional): The path to write the secrets file.
    """

    api_key = overrides.get(env.API_KEY, Api().api_key)
    if api_key is None:
        raise ValueError(
            "Can't find W&B ApiKey, set the WANDB_API_KEY env variable or run `wandb login`")
    overrides[env.API_KEY] = api_key
    with open(os.path.join(path, "secrets.env"), "w") as file:
        for k, v in six.iteritems(overrides):
            file.write("{}={}\n".format(k, v))


def join():
    # no-op until it's overridden in _init_headless
    pass


def init(job_type=None, dir=None, config=None, project=None, entity=None, reinit=None, tags=None,
         group=None, allow_val_change=False, resume=False, force=False, tensorboard=False,
         sync_tensorboard=False, name=None, notes=None, id=None, magic=None):
    """Initialize W&B

    If called from within Jupyter, initializes a new run and waits for a call to
    `wandb.log` to begin pushing metrics.  Otherwise, spawns a new process
    to communicate with W&B.

    Args:
        job_type (str, optional): The type of job running, defaults to 'train'
        config (dict, argparse, or tf.FLAGS, optional): The hyper parameters to store with the run
        project (str, optional): The project to push metrics to
        entity (str, optional): The entity to push metrics to
        dir (str, optional): An absolute path to a directory where metadata will be stored
        group (str, optional): A unique string shared by all runs in a given group
        tags (list, optional): A list of tags to apply to the run
        id (str, optional): A globally unique (per project) identifier for the run
        name (str, optional): A display name which does not have to be unique
        notes (str, optional): A multiline string associated with the run
        reinit (bool, optional): Allow multiple calls to init in the same process
        resume (bool, str, optional): Automatically resume this run if run from the same machine,
            you can also pass a unique run_id
        sync_tensorboard (bool, optional): Synchronize wandb logs to tensorboard or tensorboardX
        force (bool, optional): Force authentication with wandb, defaults to False
        magic (bool, dict, or str, optional): magic configuration as bool, dict, json string,
            yaml filename

    Returns:
        A wandb.run object for metric and config logging.
    """
    trigger.call('on_init', **locals())
    global run
    global __stage_dir__

    # We allow re-initialization when we're in Jupyter or explicity opt-in to it.
    in_jupyter = _get_python_type() != "python"
    if reinit or (in_jupyter and reinit != False):
        reset_env(exclude=env.immutable_keys())
        run = None

    # TODO: deprecate tensorboard
    if tensorboard or sync_tensorboard:
        util.get_module("wandb.tensorboard").patch()

    sagemaker_config = util.parse_sm_config()
    tf_config = util.parse_tfjob_config()
    if group == None:
        group = os.getenv(env.RUN_GROUP)
    if job_type == None:
        job_type = os.getenv(env.JOB_TYPE)
    if sagemaker_config:
        # Set run_id and potentially grouping if we're in SageMaker
        run_id = os.getenv('TRAINING_JOB_NAME')
        if run_id:
            os.environ[env.RUN_ID] = '-'.join([
                run_id,
                os.getenv('CURRENT_HOST', socket.gethostname())])
        conf = json.load(
            open("/opt/ml/input/config/resourceconfig.json"))
        if group == None and len(conf["hosts"]) > 1:
            group = os.getenv('TRAINING_JOB_NAME')
        # Set secret variables
        if os.path.exists("secrets.env"):
            for line in open("secrets.env", "r"):
                key, val = line.strip().split('=', 1)
                os.environ[key] = val
    elif tf_config:
        cluster = tf_config.get('cluster')
        job_name = tf_config.get('task', {}).get('type')
        task_index = tf_config.get('task', {}).get('index')
        if job_name is not None and task_index is not None:
            # TODO: set run_id for resuming?
            run_id = cluster[job_name][task_index].rsplit(":")[0]
            if job_type == None:
                job_type = job_name
            if group == None and len(cluster.get("worker", [])) > 0:
                group = cluster[job_name][0].rsplit("-"+job_name, 1)[0]
    image = util.image_id_from_k8s()
    if image:
        os.environ[env.DOCKER] = image
    if project:
        os.environ[env.PROJECT] = project
    if entity:
        os.environ[env.ENTITY] = entity
    if group:
        os.environ[env.RUN_GROUP] = group
    if job_type:
        os.environ[env.JOB_TYPE] = job_type
    if tags:
        os.environ[env.TAGS] = ",".join(tags)
    if id:
        os.environ[env.RUN_ID] = id
        if name is None:
            # We do this because of https://github.com/wandb/core/issues/2170
            # to ensure that the run's name is explicitly set to match its
            # id. If we don't do this and the id is eight characters long, the
            # backend will set the name to a generated human-friendly value.
            #
            # In any case, if the user is explicitly setting `id` but not
            # `name`, their id is probably a meaningful string that we can
            # use to label the run.
            name = os.environ.get(env.NAME, id)  # environment variable takes precedence over this.
    if name:
        os.environ[env.NAME] = name
    if notes:
        os.environ[env.NOTES] = notes
    if magic is not None and magic is not False:
        if isinstance(magic, dict):
            os.environ[env.MAGIC] = json.dumps(magic)
        elif isinstance(magic, str):
            os.environ[env.MAGIC] = magic
        elif isinstance(magic, bool):
            pass
        else:
            termwarn("wandb.init called with invalid magic parameter type", repeat=False)
        from wandb import magic_impl
        magic_impl.magic_install()
    if dir:
        os.environ[env.DIR] = dir
        util.mkdir_exists_ok(wandb_dir())
    resume_path = os.path.join(wandb_dir(), wandb_run.RESUME_FNAME)
    if resume == True:
        os.environ[env.RESUME] = "auto"
    elif resume:
        os.environ[env.RESUME] = os.environ.get(env.RESUME, "allow")
        # TODO: remove allowing resume as a string in the future
        os.environ[env.RUN_ID] = id or resume
    elif os.path.exists(resume_path):
        os.remove(resume_path)
    if os.environ.get(env.RESUME) == 'auto' and os.path.exists(resume_path):
        if not os.environ.get(env.RUN_ID):
            os.environ[env.RUN_ID] = json.load(open(resume_path))["run_id"]

    # the following line is useful to ensure that no W&B logging happens in the user
    # process that might interfere with what they do
    # logging.basicConfig(format='user process %(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # If a thread calls wandb.init() it will get the same Run object as
    # the parent. If a child process with distinct memory space calls
    # wandb.init(), it won't get an error, but it will get a result of
    # None.
    # This check ensures that a child process can safely call wandb.init()
    # after a parent has (only the parent will create the Run object).
    # This doesn't protect against the case where the parent doesn't call
    # wandb.init but two children do.
    if run or os.getenv(env.INITED):
        return run

    if __stage_dir__ is None:
        __stage_dir__ = "wandb"
        util.mkdir_exists_ok(wandb_dir())

    try:
        signal.signal(signal.SIGQUIT, _debugger)
    except AttributeError:
        pass

    try:
        run = wandb_run.Run.from_environment_or_defaults()
    except IOError as e:
        termerror('Failed to create run directory: {}'.format(e))
        raise LaunchError("Could not write to filesystem.")

    run.set_environment()

    def set_global_config(run):
        global config  # because we already have a local config
        config = run.config
    set_global_config(run)
    global summary
    summary = run.summary

    # set this immediately after setting the run and the config. if there is an
    # exception after this it'll probably break the user script anyway
    os.environ[env.INITED] = '1'

    # we do these checks after setting the run and the config because users scripts
    # may depend on those things
    if sys.platform == 'win32' and run.mode != 'clirun':
        termerror(
            'To use wandb on Windows, you need to run the command "wandb run python <your_train_script>.py"')
        return run

    if in_jupyter:
        _init_jupyter(run)
    elif run.mode == 'clirun':
        pass
    elif run.mode == 'run':
        api = InternalApi()
        # let init_jupyter handle this itself
        if not in_jupyter and not api.api_key:
            termlog(
                "W&B is a tool that helps track and visualize machine learning experiments")
            if force:
                termerror(
                    "No credentials found.  Run \"wandb login\" or \"wandb off\" to disable wandb")
            else:
                termlog(
                    "No credentials found.  Run \"wandb login\" to visualize your metrics")
                run.mode = "dryrun"
                _init_headless(run, False)
        else:
            _init_headless(run)
    elif run.mode == 'dryrun':
        termlog(
            'Dry run mode, not syncing to the cloud.')
        _init_headless(run, False)
    else:
        termerror(
            'Invalid run mode "%s". Please unset WANDB_MODE.' % run.mode)
        raise LaunchError("The WANDB_MODE environment variable is invalid.")

    # set the run directory in the config so it actually gets persisted
    run.config.set_run_dir(run.dir)

    if sagemaker_config:
        run.config.update(sagemaker_config)
        allow_val_change = True
    if config:
        run.config.update(config, allow_val_change=allow_val_change)

    # Access history to ensure resumed is set when resuming
    run.history
    # Load the summary to support resuming
    run.summary.load()

    atexit.register(run.close_files)

    return run


tensorflow = util.LazyLoader('tensorflow', globals(), 'wandb.tensorflow')
tensorboard = util.LazyLoader('tensorboard', globals(), 'wandb.tensorboard')
jupyter = util.LazyLoader('jupyter', globals(), 'wandb.jupyter')
keras = util.LazyLoader('keras', globals(), 'wandb.keras')
fastai = util.LazyLoader('fastai', globals(), 'wandb.fastai')
docker = util.LazyLoader('docker', globals(), 'wandb.docker')
xgboost = util.LazyLoader('xgboost', globals(), 'wandb.xgboost')


__all__ = ['init', 'config', 'termlog', 'termwarn', 'termerror', 'tensorflow',
           'run', 'types', 'callbacks', 'join']
