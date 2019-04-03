from __future__ import print_function
from __future__ import absolute_import
from __future__ import division

import base64
import errno
import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import random
import stat
import shortuuid
import importlib
import types
import yaml
from datetime import date, datetime

import click
import requests
import six
from six.moves import queue
import textwrap
from sys import getsizeof
from collections import namedtuple
from importlib import import_module
import sentry_sdk
from sentry_sdk import capture_exception
from sentry_sdk import capture_message
from wandb.env import error_reporting_enabled

import wandb
import wandb.core
from wandb import io_wrap
from wandb import wandb_dir
from wandb.apis import CommError
from wandb import wandb_config

DATA_FRAMES_SUBDIR = os.path.join('media', 'data_frames')

logger = logging.getLogger(__name__)
_not_importable = set()


# these match the environments for gorilla
if wandb.core.IS_GIT:
    SENTRY_ENV = 'development'
else:
    SENTRY_ENV = 'production'


sentry_sdk.init("https://f84bb3664d8e448084801d9198b771b2@sentry.io/1299483",
                release=wandb.__version__,
                default_integrations=False,
                environment=SENTRY_ENV)


def sentry_message(message):
    if error_reporting_enabled():
        capture_message(message)


def sentry_exc(exc):
    if error_reporting_enabled():
        if isinstance(exc, six.string_types):
            capture_exception(Exception(exc))
        else:
            capture_exception(exc)


def sentry_reraise(exc):
    """Re-raise an exception after logging it to Sentry

    Use this for top-level exceptions when you want the user to see the traceback.

    Must be called from within an exception handler.
    """
    sentry_exc(exc)
    # this will messily add this "reraise" function to the stack trace
    # but hopefully it's not too bad
    six.reraise(type(exc), exc, sys.exc_info()[2])


def vendor_import(name):
    """This enables us to use the vendor directory for packages we don't depend on"""
    parent_dir = os.path.abspath(os.path.dirname(__file__))
    vendor_dir = os.path.join(parent_dir, 'vendor')

    sys.path.insert(1, vendor_dir)
    return import_module(name)


def get_module(name, required=None):
    """
    Return module or None. Absolute import is required.
    :param (str) name: Dot-separated module path. E.g., 'scipy.stats'.
    :param (str) required: A string to raise a ValueError if missing
    :return: (module|None) If import succeeds, the module will be returned.
    """
    if name not in _not_importable:
        try:
            return import_module(name)
        except ImportError:
            _not_importable.add(name)
            if required:
                raise ValueError(required)
        except Exception as e:
            _not_importable.add(name)
            msg = "Error importing optional module {}".format(name)
            logger.exception(msg)


class LazyLoader(types.ModuleType):
    """Lazily import a module, mainly to avoid pulling in large dependencies.
    we use this for tensorflow and other optional libraries primarily at the top module level
    """

    # The lint error here is incorrect.
    def __init__(self, local_name, parent_module_globals, name, warning=None):  # pylint: disable=super-on-old-class
        self._local_name = local_name
        self._parent_module_globals = parent_module_globals
        self._warning = warning

        super(LazyLoader, self).__init__(name)

    def _load(self):
        """Load the module and insert it into the parent's globals."""
        # Import the target module and insert it into the parent's namespace
        module = importlib.import_module(self.__name__)
        self._parent_module_globals[self._local_name] = module

        # Emit a warning if one was specified
        if self._warning:
            print(self._warning)
            # Make sure to only warn once.
            self._warning = None

        # Update this object's dict so that if someone keeps a reference to the
        #   LazyLoader, lookups are efficient (__getattr__ is only called on lookups
        #   that fail).
        self.__dict__.update(module.__dict__)

        return module

    def __getattr__(self, item):
        module = self._load()
        return getattr(module, item)

    def __dir__(self):
        module = self._load()
        return dir(module)


np = get_module('numpy')

MAX_SLEEP_SECONDS = 60 * 5
# TODO: Revisit these limits
VALUE_BYTES_LIMIT = 100000


def get_full_typename(o):
    """We determine types based on type names so we don't have to import
    (and therefore depend on) PyTorch, TensorFlow, etc.
    """
    instance_name = o.__class__.__module__ + "." + o.__class__.__name__
    if instance_name in ["builtins.module", "__builtin__.module"]:
        return o.__name__
    else:
        return instance_name


def get_h5_typename(o):
    typename = get_full_typename(o)
    if is_tf_tensor_typename(typename):
        return "tensorflow.Tensor"
    elif is_pytorch_tensor_typename(typename):
        return "torch.Tensor"
    else:
        return o.__class__.__module__.split('.')[0] + "." + o.__class__.__name__


def is_tf_tensor(obj):
    import tensorflow
    return isinstance(obj, tensorflow.Tensor)


def is_tf_tensor_typename(typename):
    return typename.startswith('tensorflow.') and ('Tensor' in typename or 'Variable' in typename)


def is_pytorch_tensor(obj):
    import torch
    return isinstance(obj, torch.Tensor)


def is_pytorch_tensor_typename(typename):
    return typename.startswith('torch.') and ('Tensor' in typename or 'Variable' in typename)


def is_pandas_data_frame_typename(typename):
    return typename.startswith('pandas.') and 'DataFrame' in typename


def is_matplotlib_typename(typename):
    return typename.startswith("matplotlib.")


def is_plotly_typename(typename):
    return typename.startswith("plotly.")


def is_pandas_data_frame(obj):
    return is_pandas_data_frame_typename(get_full_typename(obj))


def ensure_matplotlib_figure(obj):
    """Extract the current figure from a matplotlib object or return the object if it's a figure.
    raises ValueError if the object can't be converted.
    """
    import matplotlib
    from matplotlib.figure import Figure
    if obj == matplotlib.pyplot:
        obj = obj.gcf()
    elif not isinstance(obj, Figure):
        if hasattr(obj, "figure"):
            obj = obj.figure
            # Some matplotlib objects have a figure function
            if not isinstance(obj, Figure):
                raise ValueError(
                    "Only matplotlib.pyplot or matplotlib.pyplot.Figure objects are accepted.")
    if not obj.gca().has_data():
        raise ValueError(
            "You attempted to log an empty plot, pass a figure directly or ensure the global plot isn't closed.")
    return obj


def json_friendly(obj):
    """Convert an object into something that's more becoming of JSON"""
    converted = True
    typename = get_full_typename(obj)

    if is_tf_tensor_typename(typename):
        obj = obj.eval()
    elif is_pytorch_tensor_typename(typename):
        try:
            if obj.requires_grad:
                obj = obj.detach()
        except AttributeError:
            pass  # before 0.4 is only present on variables

        try:
            obj = obj.data
        except RuntimeError:
            pass  # happens for Tensors before 0.4

        if obj.size():
            obj = obj.numpy()
        else:
            return obj.item(), True

    if np and isinstance(obj, np.ndarray):
        if obj.size == 1:
            obj = obj.flatten()[0]
        elif obj.size <= 32:
            obj = obj.tolist()
    elif np and isinstance(obj, np.generic):
        obj = obj.item()
    elif isinstance(obj, bytes):
        obj = obj.decode('utf-8')
    elif isinstance(obj, (datetime, date)):
        obj = obj.isoformat()
    else:
        converted = False
    if getsizeof(obj) > VALUE_BYTES_LIMIT:
        logger.warning("Object %s is %i bytes", obj, getsizeof(obj))

    return obj, converted


def convert_plots(obj):
    if is_matplotlib_typename(get_full_typename(obj)):
        tools = get_module(
            "plotly.tools", required="plotly is required to log interactive plots, install with: pip install plotly or convert the plot to an image with `wandb.Image(plt)`")
        obj = tools.mpl_to_plotly(obj)

    if is_plotly_typename(get_full_typename(obj)):
        return {"_type": "plotly", "plot": obj.to_plotly_json()}
    else:
        return obj


def maybe_compress_history(obj):
    if np and isinstance(obj, np.ndarray) and obj.size > 32:
        return wandb.Histogram(obj, num_bins=32).to_json(), True
    else:
        return obj, False


def maybe_compress_summary(obj, h5_typename):
    if np and isinstance(obj, np.ndarray) and obj.size > 32:
        return {
            "_type": h5_typename,  # may not be ndarray
            "var": np.var(obj).item(),
            "mean": np.mean(obj).item(),
            "min": np.amin(obj).item(),
            "max": np.amax(obj).item(),
            "10%": np.percentile(obj, 10),
            "25%": np.percentile(obj, 25),
            "75%": np.percentile(obj, 75),
            "90%": np.percentile(obj, 90),
            "size": obj.size
        }, True
    else:
        return obj, False


def launch_browser(attempt_launch_browser=True):
    """Decide if we should launch a browser"""
    _DISPLAY_VARIABLES = ['DISPLAY', 'WAYLAND_DISPLAY', 'MIR_SOCKET']
    _WEBBROWSER_NAMES_BLACKLIST = [
        'www-browser', 'lynx', 'links', 'elinks', 'w3m']

    import webbrowser

    launch_browser = attempt_launch_browser
    if launch_browser:
        if ('linux' in sys.platform and
                not any(os.getenv(var) for var in _DISPLAY_VARIABLES)):
            launch_browser = False
        try:
            browser = webbrowser.get()
            if (hasattr(browser, 'name')
                    and browser.name in _WEBBROWSER_NAMES_BLACKLIST):
                launch_browser = False
        except webbrowser.Error:
            launch_browser = False

    return launch_browser


def generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(alphabet=list(
        "0123456789abcdefghijklmnopqrstuvwxyz"))
    return run_gen.random(8)


def parse_tfjob_config():
    """Attempts to parse TFJob config, returning False if it can't find it"""
    if os.getenv("TF_CONFIG"):
        try:
            return json.loads(os.environ["TF_CONFIG"])
        except ValueError:
            return False
    else:
        return False


def parse_sm_config():
    """Attempts to parse SageMaker configuration returning False if it can't find it"""
    sagemaker_config = "/opt/ml/input/config/hyperparameters.json"
    if os.path.exists(sagemaker_config):
        conf = {}
        conf["sagemaker_training_job_name"] = os.getenv('TRAINING_JOB_NAME')
        # Hyper-parameter searchs quote configs...
        for k, v in six.iteritems(json.load(open(sagemaker_config))):
            cast = v.strip('"')
            if os.getenv("WANDB_API_KEY") is None and k == "wandb_api_key":
                os.environ["WANDB_API_KEY"] = cast
            else:
                if re.match(r'^[-\d]+$', cast):
                    cast = int(cast)
                elif re.match(r'^[-.\d]+$', cast):
                    cast = float(cast)
                conf[k] = cast
        return conf
    else:
        return False


class WandBJSONEncoder(json.JSONEncoder):
    """A JSON Encoder that handles some extra types."""

    def default(self, obj):
        tmp_obj, converted = json_friendly(obj)
        tmp_obj, compressed = maybe_compress_summary(
            tmp_obj, get_h5_typename(obj))
        if converted:
            return tmp_obj
        return json.JSONEncoder.default(self, tmp_obj)


class WandBHistoryJSONEncoder(json.JSONEncoder):
    """A JSON Encoder that handles some extra types.  
    This encoder turns numpy like objects with a size > 32 into histograms"""

    def default(self, obj):
        obj, converted = json_friendly(obj)
        obj, compressed = maybe_compress_history(obj)
        if converted:
            return obj
        return json.JSONEncoder.default(self, obj)


def json_dumps_safer(obj, **kwargs):
    """Convert obj to json, with some extra encodable types."""
    return json.dumps(obj, cls=WandBJSONEncoder, **kwargs)


def json_dumps_safer_history(obj, **kwargs):
    """Convert obj to json, with some extra encodable types, including histograms"""
    return json.dumps(obj, cls=WandBHistoryJSONEncoder, **kwargs)


def encode_data_frame(name, df, run):
    """Encode a Pandas DataFrame into the JSON/backend format.

    Writes the data to a file and returns a dictionary that we use to represent
    it in `Summary`'s.

    Arguments:
        name (str): Name of the DataFrame, eg. the summary key in which it's
            stored. This is for convenience, so people exploring the
            directory tree can have some idea of what is in the Parquet files.
        df (pandas.DataFrame): The DataFrame. Must not have columns named
            "wandb_run_id" or "wandb_data_frame_id". They will be added to the
            DataFrame here.
        run (wandb_run.Run): The Run the DataFrame is associated with. We need
            this because the information we store on the DataFrame is derived
            from the Run it's in.

    Returns:
        A dict representing the DataFrame that we can store in summaries or
        histories. This is the format:
        {
            '_type': 'data-frame',
                # Magic field that indicates that this object is a data frame as
                # opposed to a normal dictionary or anything else.
            'id': 'asdf',
                # ID for the data frame that is unique to this Run.
            'format': 'parquet',
                # The file format in which the data frame is stored. Currently can
                # only be Parquet.
            'current_project_name': 'wfeas',
                # (Current) name of the project that this Run is in. It'd be
                # better to store the project's ID because we know it'll never
                # change but we don't have that here. We store this just in
                # case because we use the project name in identifiers on the
                # backend.
            'path': 'media/data_frames/sdlk.parquet',
                # Path to the Parquet file in the Run directory.
        }
    """
    pandas = get_module("pandas")
    fastparquet = get_module("fastparquet")
    if not pandas or not fastparquet:
        raise wandb.Error("Failed to save data frame: unable to import either pandas or fastparquet.")

    data_frame_id = generate_id()

    # We have to call this wandb_run_id because that name is treated specially by
    # our filtering code
    df['wandb_run_id'] = pandas.Series(
        [six.text_type(run.name)] * len(df.index), index=df.index)

    df['wandb_data_frame_id'] = pandas.Series(
        [six.text_type(data_frame_id)] * len(df.index), index=df.index)
    frames_dir = os.path.join(run.dir, DATA_FRAMES_SUBDIR)
    mkdir_exists_ok(frames_dir)
    path = os.path.join(frames_dir, '{}-{}.parquet'.format(name, data_frame_id))
    fastparquet.write(path, df)

    return {
        'id': data_frame_id,
        '_type': 'data-frame',
        'format': 'parquet',
        'current_project_name': run.project_name(),  # we don't have the project ID here
        'path': path,
    }


def make_json_if_not_number(v):
    """If v is not a basic type convert it to json."""
    if isinstance(v, (float, int)):
        return v
    return json_dumps_safer(v)


def mkdir_exists_ok(path):
    try:
        os.makedirs(path)
        return True
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            return False
        else:
            raise


def no_retry_auth(e):
    if hasattr(e, "exception"):
        e = e.exception
    if not isinstance(e, requests.HTTPError):
        return True
    # Don't retry bad request errors; raise immediately
    if e.response.status_code == 400:
        return False
    # Retry all non-forbidden/unauthorized errors.
    if e.response.status_code not in (401, 403):
        return True
    # Crash w/message on forbidden/unauthorized errors.
    raise CommError("Invalid or missing api_key.  Run wandb login")


def write_settings(entity, project, url):
    if not os.path.isdir(wandb_dir()):
        os.mkdir(wandb_dir())
    with open(os.path.join(wandb_dir(), 'settings'), "w") as file:
        print('[default]', file=file)
        print('entity: {}'.format(entity), file=file)
        print('project: {}'.format(project), file=file)
        print('base_url: {}'.format(url), file=file)


def write_netrc(host, entity, key):
    """Add our host and key to .netrc"""
    if len(key) != 40:
        click.secho(
            'API-key must be exactly 40 characters long: {} ({} chars)'.format(key, len(key)))
        return None
    try:
        normalized_host = host.split("/")[-1].split(":")[0]
        print("Appending key for %s to your netrc file: %s" %
              (normalized_host, os.path.expanduser('~/.netrc')))
        machine_line = 'machine %s' % normalized_host
        path = os.path.expanduser('~/.netrc')
        orig_lines = None
        try:
            with open(path) as f:
                orig_lines = f.read().strip().split('\n')
        except (IOError, OSError) as e:
            pass
        with open(path, 'w') as f:
            if orig_lines:
                # delete this machine from the file if it's already there.
                skip = 0
                for line in orig_lines:
                    if machine_line in line:
                        skip = 2
                    elif skip:
                        skip -= 1
                    else:
                        f.write('%s\n' % line)
            f.write(textwrap.dedent("""\
            machine {host}
              login {entity}
              password {key}
            """).format(host=normalized_host, entity=entity, key=key))
        os.chmod(os.path.expanduser('~/.netrc'),
                 stat.S_IRUSR | stat.S_IWUSR)
        return True
    except IOError as e:
        click.secho("Unable to read ~/.netrc", fg="red")
        return None


def request_with_retry(func, *args, **kwargs):
    """Perform a requests http call, retrying with exponential backoff.

    Args:
        func: An http-requesting function to call, like requests.post
        max_retries: Maximum retries before giving up. By default we retry 30 times in ~2 hours before dropping the chunk
        *args: passed through to func
        **kwargs: passed through to func
    """
    max_retries = kwargs.pop('max_retries', 30)
    sleep = 2
    retry_count = 0
    while True:
        try:
            response = func(*args, **kwargs)
            response.raise_for_status()
            return response
        except (requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,  # XXX 500s aren't retryable
                requests.exceptions.Timeout) as e:
            if retry_count == max_retries:
                return e
            retry_count += 1
            delay = sleep + random.random() * 0.25 * sleep
            if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 429:
                logger.info(
                    "Rate limit exceeded, retrying in %s seconds" % delay)
            else:
                logger.warning('requests_with_retry encountered retryable exception: %s. args: %s, kwargs: %s',
                               e, args, kwargs)
            time.sleep(delay)
            sleep *= 2
            if sleep > MAX_SLEEP_SECONDS:
                sleep = MAX_SLEEP_SECONDS
        except requests.exceptions.RequestException as e:
            logger.error(response.json()['error'])  # XXX clean this up
            logger.exception(
                'requests_with_retry encountered unretryable exception: %s', e)
            return e


def find_runner(program):
    """Return a command that will run program.

    Args:
        program: The string name of the program to try to run.
    Returns:
        commandline list of strings to run the program (eg. with subprocess.call()) or None
    """
    if os.path.isfile(program) and not os.access(program, os.X_OK):
        # program is a path to a non-executable file
        try:
            opened = open(program)
        except PermissionError:
            return None
        first_line = opened.readline().strip()
        if first_line.startswith('#!'):
            return shlex.split(first_line[2:])
        if program.endswith('.py'):
            return [sys.executable]
    return None


def downsample(values, target_length):
    """Downsamples 1d values to target_length, including start and end.

    Algorithm just rounds index down.

    Values can be any sequence, including a generator.
    """
    assert target_length > 1
    values = list(values)
    if len(values) < target_length:
        return values
    ratio = float(len(values) - 1) / (target_length - 1)
    result = []
    for i in range(target_length):
        result.append(values[int(i * ratio)])
    return result


def md5_file(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return base64.b64encode(hash_md5.digest()).decode('ascii')


def get_log_file_path():
    """Log file path used in error messages.

    It would probably be better if this pointed to a log file in a
    run directory.
    """
    return wandb.GLOBAL_LOG_FNAME

def is_wandb_file(name):
    return name.startswith('wandb') or name == wandb_config.FNAME or name == "requirements.txt"

def docker_image_regex(image):
    "regex for valid docker image names"
    if image:
        return re.match(r"^(?:(?=[^:\/]{1,253})(?!-)[a-zA-Z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-zA-Z0-9-]{1,63}(?<!-))*(?::[0-9]{1,5})?/)?((?![._-])(?:[a-z0-9._-]*)(?<![._-])(?:/(?![._-])[a-z0-9._-]*(?<![._-]))*)(?::(?![.-])[a-zA-Z0-9_.-]{1,128})?$", image)

def image_from_docker_args(args):
    """This scans docker run args and attempts to find the most likely docker image argument.
    If excludes any argments that start with a dash, and the argument after it if it isn't a boolean
    switch.  This can be improved, we currently fallback gracefully when this fails.
    """
    bool_args = ["-t", "--tty", "--rm","--privileged", "--oom-kill-disable","--no-healthcheck", "-i",
        "--interactive", "--init", "--help", "--detach", "-d", "--sig-proxy", "-it", "-itd"]
    last_flag = -2
    last_arg = ""
    possible_images = []
    if len(args) > 0 and args[0] == "run":
        args.pop(0)
    for i, arg in enumerate(args):
        if arg.startswith("-"):
            last_flag = i
            last_arg = arg
        elif "@sha256:" in arg:
            # Because our regex doesn't match digests
            possible_images.append(arg)
        elif docker_image_regex(arg):
            if last_flag == i - 2:
                possible_images.append(arg)
            elif "=" in last_arg:
                possible_images.append(arg)
            elif last_arg in bool_args and last_flag == i - 1:
                possible_images.append(arg)
    most_likely = None
    for img in possible_images:
        if ":" in img or "@" in img or "/" in img:
            most_likely = img
            break
    if most_likely == None and len(possible_images) > 0:
        most_likely = possible_images[0]
    return most_likely


def load_yaml(file):
    """If pyyaml > 5.1 use full_load to avoid warning"""
    if hasattr(yaml, "full_load"):
        return yaml.full_load(file)
    else:
        return yaml.load(file)

def image_id_from_k8s():
    """Pings the k8s metadata service for the image id"""
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if os.path.exists(token_path):
        k8s_server = "https://{}:{}/api/v1/namespaces/default/pods/{}".format(
            os.getenv("KUBERNETES_SERVICE_HOST"), os.getenv(
                "KUBERNETES_PORT_443_TCP_PORT"), os.getenv("HOSTNAME")
        )
        try:
            res = requests.get(k8s_server, verify="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
                               timeout=3, headers={"Authorization": "Bearer {}".format(open(token_path).read())})
            res.raise_for_status()
        except requests.RequestException:
            return None
        try:
            return res.json()["status"]["containerStatuses"][0]["imageID"].strip("docker-pullable://")
        except (ValueError, KeyError, IndexError):
            logger.exception("Error checking kubernetes for image id")
            return None


def async_call(target, timeout=None):
    """Accepts a method and optional timeout.
       Returns a new method that will call the original with any args, waiting for upto timeout seconds.
       This new method blocks on the original and returns the result or None
       if timeout was reached, along with the thread.
       You can check thread.isAlive() to determine if a timeout was reached.
       If an exception is thrown in the thread, we reraise it.
    """
    q = queue.Queue()
    def wrapped_target(q, *args, **kwargs):
        try:
            q.put(target(*args, **kwargs))
        except Exception as e:
            q.put(e)

    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=wrapped_target, args=(q,)+args, kwargs=kwargs)
        thread.daemon = True
        thread.start()
        try:
            result = q.get(True, timeout)
            if isinstance(result, Exception):
                six.reraise(type(result), result, sys.exc_info()[2])
            return result, thread
        except queue.Empty:
            return None, thread
    return wrapper

def read_many_from_queue(q, max_items, queue_timeout):
    try:
        item = q.get(True, queue_timeout)
    except queue.Empty:
        return []
    items = [item]
    for i in range(max_items):
        try:
            item = q.get_nowait()
        except queue.Empty:
            return items
        items.append(item)
    return items

def stopwatch_now():
    """Get a timevalue for interval comparisons

    When possible it is a monotonic clock to prevent backwards time issues.
    """
    if six.PY2:
        now = time.time()
    else:
        now = time.monotonic()
    return now
