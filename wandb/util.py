from __future__ import print_function
from __future__ import absolute_import
from __future__ import division

import base64
import binascii
import colorsys
import contextlib
import codecs
import errno
import hashlib
import json
import getpass
import logging
import math
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
import platform
from six.moves.urllib.parse import urlparse

import click
import requests
import six
from six.moves import queue
import textwrap
from sys import getsizeof
from collections import namedtuple
from six.moves.collections_abc import Mapping, Sequence
from importlib import import_module
import sentry_sdk
from sentry_sdk import capture_exception
from sentry_sdk import capture_message
from sentry_sdk import configure_scope
from wandb.env import error_reporting_enabled

import wandb
from wandb.old.core import wandb_dir
from wandb.errors.error import CommError
from wandb import env

logger = logging.getLogger(__name__)
_not_importable = set()


IS_GIT = os.path.exists(os.path.join(os.path.dirname(__file__), "..", ".git"))

# these match the environments for gorilla
if IS_GIT:
    SENTRY_ENV = "development"
else:
    SENTRY_ENV = "production"

if error_reporting_enabled():
    sentry_sdk.init(
        dsn="https://a2f1d701163c42b097b9588e56b1c37e@o151352.ingest.sentry.io/5288891",
        release=wandb.__version__,
        default_integrations=False,
        environment=SENTRY_ENV,
    )


def sentry_message(message):
    if error_reporting_enabled():
        capture_message(message)


def sentry_exc(exc, delay=False):
    if error_reporting_enabled():
        if isinstance(exc, six.string_types):
            capture_exception(Exception(exc))
        else:
            capture_exception(exc)
        if delay:
            time.sleep(2)


def sentry_reraise(exc):
    """Re-raise an exception after logging it to Sentry

    Use this for top-level exceptions when you want the user to see the traceback.

    Must be called from within an exception handler.
    """
    sentry_exc(exc)
    # this will messily add this "reraise" function to the stack trace
    # but hopefully it's not too bad
    six.reraise(type(exc), exc, sys.exc_info()[2])


def sentry_set_scope(process_context, entity, project, email=None, url=None):
    # Using GLOBAL_HUB means these tags will persist between threads.
    # Normally there is one hub per thread.
    with sentry_sdk.hub.GLOBAL_HUB.configure_scope() as scope:
        scope.set_tag("process_context", process_context)
        scope.set_tag("entity", entity)
        scope.set_tag("project", project)
        if email:
            scope.user = {"email": email}
        if url:
            scope.set_tag("url", url)


def vendor_setup():
    """This enables us to use the vendor directory for packages we don't depend on
    Returns a function to call after imports are complete. Make sure to call this
    function or you will modify the user's path which is never good. The pattern should be:
    reset_path = vendor_setup()
    # do any vendor imports...
    reset_path()
    """
    original_path = [directory for directory in sys.path]

    def reset_import_path():
        sys.path = original_path

    parent_dir = os.path.abspath(os.path.dirname(__file__))
    vendor_dir = os.path.join(parent_dir, "vendor")
    vendor_packages = (
        "gql-0.2.0",
        "graphql-core-1.1",
    )
    package_dirs = [os.path.join(vendor_dir, p) for p in vendor_packages]
    for p in [vendor_dir] + package_dirs:
        if p not in sys.path:
            sys.path.insert(1, p)

    return reset_import_path


def apple_gpu_stats_binary():
    parent_dir = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(parent_dir, "bin", "apple_gpu_stats")


def vendor_import(name):
    reset_path = vendor_setup()
    module = import_module(name)
    reset_path()
    return module


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
        except Exception as e:
            _not_importable.add(name)
            msg = "Error importing optional module {}".format(name)
            if required:
                logger.exception(msg)
    if required and name in _not_importable:
        raise wandb.Error(required)


class LazyLoader(types.ModuleType):
    """Lazily import a module, mainly to avoid pulling in large dependencies.
    we use this for tensorflow and other optional libraries primarily at the top module level
    """

    # The lint error here is incorrect.
    def __init__(
        self, local_name, parent_module_globals, name, warning=None
    ):  # pylint: disable=super-on-old-class
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


class PreInitObject(object):
    def __init__(self, name):
        self._name = name

    def __getitem__(self, key):
        raise wandb.Error(
            'You must call wandb.init() before {}["{}"]'.format(self._name, key)
        )

    def __setitem__(self, key, value):
        raise wandb.Error(
            'You must call wandb.init() before {}["{}"]'.format(self._name, key)
        )

    def __setattr__(self, key, value):
        if not key.startswith("_"):
            raise wandb.Error(
                "You must call wandb.init() before {}.{}".format(self._name, key)
            )
        else:
            return object.__setattr__(self, key, value)

    def __getattr__(self, key):
        if not key.startswith("_"):
            raise wandb.Error(
                "You must call wandb.init() before {}.{}".format(self._name, key)
            )
        else:
            raise AttributeError()


np = get_module("numpy")

MAX_SLEEP_SECONDS = 60 * 5
# TODO: Revisit these limits
VALUE_BYTES_LIMIT = 100000


def app_url(api_url):
    if "://api.wandb." in api_url:
        # cloud
        return api_url.replace("://api.", "://")
    elif "://api." in api_url:
        # onprem cloud
        return api_url.replace("://api.", "://app.")
    # wandb/local
    return api_url


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
        return o.__class__.__module__.split(".")[0] + "." + o.__class__.__name__


def is_tf_tensor(obj):
    import tensorflow

    return isinstance(obj, tensorflow.Tensor)


def is_tf_tensor_typename(typename):
    return typename.startswith("tensorflow.") and (
        "Tensor" in typename or "Variable" in typename
    )


def is_tf_eager_tensor_typename(typename):
    return typename.startswith("tensorflow.") and ("EagerTensor" in typename)


def is_pytorch_tensor(obj):
    import torch

    return isinstance(obj, torch.Tensor)


def is_pytorch_tensor_typename(typename):
    return typename.startswith("torch.") and (
        "Tensor" in typename or "Variable" in typename
    )


def is_fastai_tensor_typename(typename):
    return typename.startswith("fastai.") and ("Tensor" in typename)


def is_pandas_data_frame_typename(typename):
    return typename.startswith("pandas.") and "DataFrame" in typename


def is_matplotlib_typename(typename):
    return typename.startswith("matplotlib.")


def is_plotly_typename(typename):
    return typename.startswith("plotly.")


def is_plotly_figure_typename(typename):
    return typename.startswith("plotly.") and typename.endswith(".Figure")


def is_numpy_array(obj):
    return np and isinstance(obj, np.ndarray)


def is_pandas_data_frame(obj):
    return is_pandas_data_frame_typename(get_full_typename(obj))


def ensure_matplotlib_figure(obj):
    """Extract the current figure from a matplotlib object or return the object if it's a figure.
    raises ValueError if the object can't be converted.
    """
    import matplotlib
    from matplotlib.figure import Figure

    # plotly and matplotlib broke in recent releases,
    # this patches matplotlib to add a removed method that plotly assumes exists
    from matplotlib.spines import Spine

    def is_frame_like(self):
        """Return True if directly on axes frame.

        This is useful for determining if a spine is the edge of an
        old style MPL plot. If so, this function will return True.
        """
        position = self._position or ("outward", 0.0)
        if isinstance(position, str):
            if position == "center":
                position = ("axes", 0.5)
            elif position == "zero":
                position = ("data", 0)
        if len(position) != 2:
            raise ValueError("position should be 2-tuple")
        position_type, amount = position
        if position_type == "outward" and amount == 0:
            return True
        else:
            return False

    Spine.is_frame_like = is_frame_like
    if obj == matplotlib.pyplot:
        obj = obj.gcf()
    elif not isinstance(obj, Figure):
        if hasattr(obj, "figure"):
            obj = obj.figure
            # Some matplotlib objects have a figure function
            if not isinstance(obj, Figure):
                raise ValueError(
                    "Only matplotlib.pyplot or matplotlib.pyplot.Figure objects are accepted."
                )
    return obj


def matplotlib_to_plotly(obj):
    obj = ensure_matplotlib_figure(obj)
    tools = get_module(
        "plotly.tools",
        required="plotly is required to log interactive plots, install with: pip install plotly or convert the plot to an image with `wandb.Image(plt)`",
    )
    return tools.mpl_to_plotly(obj)


def matplotlib_contains_images(obj):
    obj = ensure_matplotlib_figure(obj)
    return any(len(ax.images) > 0 for ax in obj.axes)


def json_friendly(obj):
    """Convert an object into something that's more becoming of JSON"""
    converted = True
    typename = get_full_typename(obj)

    if is_tf_eager_tensor_typename(typename):
        obj = obj.numpy()
    elif is_tf_tensor_typename(typename):
        try:
            obj = obj.eval()
        except RuntimeError:
            obj = obj.numpy()
    elif is_pytorch_tensor_typename(typename) or is_fastai_tensor_typename(typename):
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

    if is_numpy_array(obj):
        if obj.size == 1:
            obj = obj.flatten()[0]
        elif obj.size <= 32:
            obj = obj.tolist()
    elif np and isinstance(obj, np.generic):
        obj = obj.item()
        if isinstance(obj, float) and math.isnan(obj):
            obj = None
    elif isinstance(obj, bytes):
        obj = obj.decode("utf-8")
    elif isinstance(obj, (datetime, date)):
        obj = obj.isoformat()
    elif callable(obj):
        obj = (
            "{}.{}".format(obj.__module__, obj.__qualname__)
            if hasattr(obj, "__qualname__") and hasattr(obj, "__module__")
            else str(obj)
        )
    else:
        converted = False
    if getsizeof(obj) > VALUE_BYTES_LIMIT:
        wandb.termwarn(
            "Serializing object of type {} that is {} bytes".format(
                type(obj).__name__, getsizeof(obj)
            )
        )

    return obj, converted


def convert_plots(obj):
    if is_matplotlib_typename(get_full_typename(obj)):
        tools = get_module(
            "plotly.tools",
            required="plotly is required to log interactive plots, install with: pip install plotly or convert the plot to an image with `wandb.Image(plt)`",
        )
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
        return (
            {
                "_type": h5_typename,  # may not be ndarray
                "var": np.var(obj).item(),
                "mean": np.mean(obj).item(),
                "min": np.amin(obj).item(),
                "max": np.amax(obj).item(),
                "10%": np.percentile(obj, 10),
                "25%": np.percentile(obj, 25),
                "75%": np.percentile(obj, 75),
                "90%": np.percentile(obj, 90),
                "size": obj.size,
            },
            True,
        )
    else:
        return obj, False


def launch_browser(attempt_launch_browser=True):
    """Decide if we should launch a browser"""
    _DISPLAY_VARIABLES = ["DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"]
    _WEBBROWSER_NAMES_BLACKLIST = ["www-browser", "lynx", "links", "elinks", "w3m"]

    import webbrowser

    launch_browser = attempt_launch_browser
    if launch_browser:
        if "linux" in sys.platform and not any(
            os.getenv(var) for var in _DISPLAY_VARIABLES
        ):
            launch_browser = False
        try:
            browser = webbrowser.get()
            if hasattr(browser, "name") and browser.name in _WEBBROWSER_NAMES_BLACKLIST:
                launch_browser = False
        except webbrowser.Error:
            launch_browser = False

    return launch_browser


def generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(alphabet=list("0123456789abcdefghijklmnopqrstuvwxyz"))
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


class WandBJSONEncoder(json.JSONEncoder):
    """A JSON Encoder that handles some extra types."""

    def default(self, obj):
        if hasattr(obj, "json_encode"):
            return obj.json_encode()
        # if hasattr(obj, 'to_json'):
        #     return obj.to_json()
        tmp_obj, converted = json_friendly(obj)
        if converted:
            return tmp_obj
        return json.JSONEncoder.default(self, obj)


class WandBJSONEncoderOld(json.JSONEncoder):
    """A JSON Encoder that handles some extra types."""

    def default(self, obj):
        tmp_obj, converted = json_friendly(obj)
        tmp_obj, compressed = maybe_compress_summary(tmp_obj, get_h5_typename(obj))
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


class JSONEncoderUncompressed(json.JSONEncoder):
    """A JSON Encoder that handles some extra types.
    This encoder turns numpy like objects with a size > 32 into histograms"""

    def default(self, obj):
        if is_numpy_array(obj):
            return obj.tolist()
        elif np and isinstance(obj, np.generic):
            obj = obj.item()
        return json.JSONEncoder.default(self, obj)


def json_dump_safer(obj, fp, **kwargs):
    """Convert obj to json, with some extra encodable types."""
    return json.dump(obj, fp, cls=WandBJSONEncoder, **kwargs)


def json_dumps_safer(obj, **kwargs):
    """Convert obj to json, with some extra encodable types."""
    return json.dumps(obj, cls=WandBJSONEncoder, **kwargs)


# This is used for dumping raw json into files
def json_dump_uncompressed(obj, fp, **kwargs):
    """Convert obj to json, with some extra encodable types."""
    return json.dump(obj, fp, cls=JSONEncoderUncompressed, **kwargs)


def json_dumps_safer_history(obj, **kwargs):
    """Convert obj to json, with some extra encodable types, including histograms"""
    return json.dumps(obj, cls=WandBHistoryJSONEncoder, **kwargs)


def make_json_if_not_number(v):
    """If v is not a basic type convert it to json."""
    if isinstance(v, (float, int)):
        return v
    return json_dumps_safer(v)


def make_safe_for_json(obj):
    """Replace invalid json floats with strings. Also converts to lists and dicts."""
    if isinstance(obj, Mapping):
        return {k: make_safe_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, str):
        # str's are Sequence, so we need to short-circuit
        return obj
    elif isinstance(obj, Sequence):
        return [make_safe_for_json(v) for v in obj]
    elif isinstance(obj, float):
        # W&B backend and UI handle these strings
        if obj != obj:  # standard way to check for NaN
            return "NaN"
        elif obj == float("+inf"):
            return "Infinity"
        elif obj == float("-inf"):
            return "-Infinity"
    return obj


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
    # Retry all non-forbidden/unauthorized/not-found errors.
    if e.response.status_code not in (401, 403, 404):
        return True
    # Crash w/message on forbidden/unauthorized errors.
    if e.response.status_code == 401:
        raise CommError("Invalid or missing api_key.  Run wandb login")
    elif wandb.run:
        raise CommError("Permission denied to access {}".format(wandb.run.path))
    else:
        raise CommError("Permission denied, ask the project owner to grant you access")


def request_with_retry(func, *args, **kwargs):
    """Perform a requests http call, retrying with exponential backoff.

    Arguments:
        func: An http-requesting function to call, like requests.post
        max_retries: Maximum retries before giving up. By default we retry 30 times in ~2 hours before dropping the chunk
        *args: passed through to func
        **kwargs: passed through to func
    """
    max_retries = kwargs.pop("max_retries", 30)
    sleep = 2
    retry_count = 0
    while True:
        try:
            response = func(*args, **kwargs)
            response.raise_for_status()
            return response
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
        ) as e:
            if isinstance(e, requests.exceptions.HTTPError):
                # Non-retriable HTTP errors.
                #
                # We retry 500s just to be cautious, and because the back end
                # returns them when there are infrastructure issues. If retrying
                # some request winds up being problematic, we'll change the
                # back end to indicate that it shouldn't be retried.
                if e.response.status_code in {400, 403, 404, 409} or (
                    e.response.status_code == 500
                    and e.response.content == b'{"error":"context deadline exceeded"}\n'
                ):
                    return e

            if retry_count == max_retries:
                return e
            retry_count += 1
            delay = sleep + random.random() * 0.25 * sleep
            if (
                isinstance(e, requests.exceptions.HTTPError)
                and e.response.status_code == 429
            ):
                logger.info("Rate limit exceeded, retrying in %s seconds" % delay)
            else:
                pass
                logger.warning(
                    "requests_with_retry encountered retryable exception: %s. func: %s, response: %s, args: %s, kwargs: %s",
                    e,
                    func,
                    e.response.content,
                    args,
                    kwargs,
                )
            time.sleep(delay)
            sleep *= 2
            if sleep > MAX_SLEEP_SECONDS:
                sleep = MAX_SLEEP_SECONDS
        except requests.exceptions.RequestException as e:
            logger.error(response.json()["error"])  # XXX clean this up
            logger.exception(
                "requests_with_retry encountered unretryable exception: %s", e
            )
            return e


def find_runner(program):
    """Return a command that will run program.

    Arguments:
        program: The string name of the program to try to run.
    Returns:
        commandline list of strings to run the program (eg. with subprocess.call()) or None
    """
    if os.path.isfile(program) and not os.access(program, os.X_OK):
        # program is a path to a non-executable file
        try:
            opened = open(program)
        except IOError:  # PermissionError doesn't exist in 2.7
            return None
        first_line = opened.readline().strip()
        if first_line.startswith("#!"):
            return shlex.split(first_line[2:])
        if program.endswith(".py"):
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


import numbers


def has_num(dictionary, key):
    return key in dictionary and isinstance(dictionary[key], numbers.Number)


def md5_file(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return base64.b64encode(hash_md5.digest()).decode("ascii")


def get_log_file_path():
    """Log file path used in error messages.

    It would probably be better if this pointed to a log file in a
    run directory.
    """
    # TODO(jhr, cvp): refactor
    if wandb.run:
        return wandb.run._settings.log_internal
    return os.path.join("wandb", "debug-internal.log")


def docker_image_regex(image):
    "regex for valid docker image names"
    if image:
        return re.match(
            r"^(?:(?=[^:\/]{1,253})(?!-)[a-zA-Z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-zA-Z0-9-]{1,63}(?<!-))*(?::[0-9]{1,5})?/)?((?![._-])(?:[a-z0-9._-]*)(?<![._-])(?:/(?![._-])[a-z0-9._-]*(?<![._-]))*)(?::(?![.-])[a-zA-Z0-9_.-]{1,128})?$",
            image,
        )


def image_from_docker_args(args):
    """This scans docker run args and attempts to find the most likely docker image argument.
    If excludes any argments that start with a dash, and the argument after it if it isn't a boolean
    switch.  This can be improved, we currently fallback gracefully when this fails.
    """
    bool_args = [
        "-t",
        "--tty",
        "--rm",
        "--privileged",
        "--oom-kill-disable",
        "--no-healthcheck",
        "-i",
        "--interactive",
        "--init",
        "--help",
        "--detach",
        "-d",
        "--sig-proxy",
        "-it",
        "-itd",
    ]
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
    """Pings the k8s metadata service for the image id.  Specify the
    KUBERNETES_NAMESPACE environment variable if your pods are not in
    the default namespace:

    - name: KUBERNETES_NAMESPACE
      valueFrom:
        fieldRef:
          fieldPath: metadata.namespace
    """
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if os.path.exists(token_path):
        k8s_server = "https://{}:{}/api/v1/namespaces/{}/pods/{}".format(
            os.getenv("KUBERNETES_SERVICE_HOST"),
            os.getenv("KUBERNETES_PORT_443_TCP_PORT"),
            os.getenv("KUBERNETES_NAMESPACE", "default"),
            os.getenv("HOSTNAME"),
        )
        try:
            res = requests.get(
                k8s_server,
                verify="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
                timeout=3,
                headers={"Authorization": "Bearer {}".format(open(token_path).read())},
            )
            res.raise_for_status()
        except requests.RequestException:
            return None
        try:
            return res.json()["status"]["containerStatuses"][0]["imageID"].strip(
                "docker-pullable://"
            )
        except (ValueError, KeyError, IndexError):
            logger.exception("Error checking kubernetes for image id")
            return None


def async_call(target, timeout=None):
    """Accepts a method and optional timeout.
       Returns a new method that will call the original with any args, waiting for upto timeout seconds.
       This new method blocks on the original and returns the result or None
       if timeout was reached, along with the thread.
       You can check thread.is_alive() to determine if a timeout was reached.
       If an exception is thrown in the thread, we reraise it.
    """
    q = queue.Queue()

    def wrapped_target(q, *args, **kwargs):
        try:
            q.put(target(*args, **kwargs))
        except Exception as e:
            q.put(e)

    def wrapper(*args, **kwargs):
        thread = threading.Thread(
            target=wrapped_target, args=(q,) + args, kwargs=kwargs
        )
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


def class_colors(class_count):
    # make class 0 black, and the rest equally spaced fully saturated hues
    return [[0, 0, 0]] + [
        colorsys.hsv_to_rgb(i / (class_count - 1.0), 1.0, 1.0)
        for i in range(class_count - 1)
    ]


def guess_data_type(shape, risky=False):
    """Infer the type of data based on the shape of the tensors

    Arguments:
        risky(bool): some guesses are more likely to be wrong.
    """
    # (samples,) or (samples,logits)
    if len(shape) in (1, 2):
        return "label"
    # Assume image mask like fashion mnist: (no color channel)
    # This is risky because RNNs often have 3 dim tensors: batch, time, channels
    if risky and len(shape) == 3:
        return "image"
    if len(shape) == 4:
        if shape[-1] in (1, 3, 4):
            # (samples, height, width, Y \ RGB \ RGBA)
            return "image"
        else:
            # (samples, height, width, logits)
            return "segmentation_mask"
    return None


def download_file_from_url(dest_path, source_url, api_key=None):
    response = requests.get(source_url, auth=("api", api_key), stream=True, timeout=5)
    response.raise_for_status()

    if os.sep in dest_path:
        mkdir_exists_ok(os.path.dirname(dest_path))
    with fsync_open(dest_path, "wb") as file:
        for data in response.iter_content(chunk_size=1024):
            file.write(data)


def isatty(ob):
    return hasattr(ob, "isatty") and ob.isatty()


def sizeof_fmt(num, suffix="B"):
    """Pretty print file size
        https://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
    """
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)


def auto_project_name(program):
    # if we're in git, set project name to git repo name + relative path within repo
    root_dir = wandb.wandb_sdk.lib.git.GitRepo().root_dir
    if root_dir is None:
        return "uncategorized"
    # On windows, GitRepo returns paths in unix style, but os.path is windows
    # style. Coerce here.
    root_dir = to_native_slash_path(root_dir)
    repo_name = os.path.basename(root_dir)
    if program is None:
        return repo_name
    if not os.path.isabs(program):
        program = os.path.join(os.curdir, program)
    prog_dir = os.path.dirname(os.path.abspath(program))
    if not prog_dir.startswith(root_dir):
        return repo_name
    project = repo_name
    sub_path = os.path.relpath(prog_dir, root_dir)
    if sub_path != ".":
        project += "-" + sub_path
    return project.replace(os.sep, "_")


def parse_sweep_id(parts_dict):
    """In place parse sweep path from parts dict.

    Arguments:
        parts_dict (dict): dict(entity=,project=,name=).  Modifies dict inplace.
    
    Returns:
        None or str if there is an error
    """

    entity = None
    project = None
    sweep_id = parts_dict.get("name")
    if not isinstance(sweep_id, six.string_types):
        return "Expected string sweep_id"

    sweep_split = sweep_id.split("/")
    if len(sweep_split) == 1:
        pass
    elif len(sweep_split) == 2:
        split_project, sweep_id = sweep_split
        project = split_project or project
    elif len(sweep_split) == 3:
        split_entity, split_project, sweep_id = sweep_split
        project = split_project or project
        entity = split_entity or entity
    else:
        return (
            "Expected sweep_id in form of sweep, project/sweep, or entity/project/sweep"
        )
    parts_dict.update(dict(name=sweep_id, project=project, entity=entity))


def to_forward_slash_path(path):
    if platform.system() == "Windows":
        path = path.replace("\\", "/")
    return path


def to_native_slash_path(path):
    return path.replace("/", os.sep)


def bytes_to_hex(bytestr):
    # Works in python2 / python3
    return codecs.getencoder("hex")(bytestr)[0].decode("ascii")


def check_and_warn_old(files):
    if "wandb-metadata.json" in files:
        wandb.termwarn("These runs were logged with a previous version of wandb.")
        wandb.termwarn(
            "Run pip install wandb<0.10.0 to get the old library and sync your runs."
        )
        return True
    return False


class ImportMetaHook:
    def __init__(self):
        self.modules = {}
        self.on_import = {}

    def add(self, fullname, on_import):
        self.on_import.setdefault(fullname, []).append(on_import)

    def install(self):
        sys.meta_path.insert(0, self)

    def uninstall(self):
        sys.meta_path.remove(self)

    def find_module(self, fullname, path=None):
        if fullname in self.on_import:
            return self

    def load_module(self, fullname):
        self.uninstall()
        mod = importlib.import_module(fullname)
        self.install()
        self.modules[fullname] = mod
        on_imports = self.on_import.get(fullname)
        if on_imports:
            for f in on_imports:
                f()
        return mod

    def get_modules(self):
        return tuple(self.modules)

    def get_module(self, module):
        return self.modules[module]


_import_hook = None


def add_import_hook(fullname, on_import):
    global _import_hook
    if _import_hook is None:
        _import_hook = ImportMetaHook()
        _import_hook.install()
    _import_hook.add(fullname, on_import)


def b64_to_hex_id(id_string):
    return binascii.hexlify(base64.standard_b64decode(str(id_string))).decode("utf-8")


def hex_to_b64_id(encoded_string):
    return base64.standard_b64encode(binascii.unhexlify(encoded_string)).decode("utf-8")


def host_from_path(path):
    """returns the host of the path"""
    url = urlparse(path)
    return url.netloc


def uri_from_path(path):
    """returns the URI of the path"""
    url = urlparse(path)
    return url.path if url.path[0] != "/" else url.path[1:]


@contextlib.contextmanager
def fsync_open(path, mode="w"):
    """
    Opens a path for I/O, guaranteeing that the file is flushed and
    fsynced when the file's context expires.
    """
    with open(path, mode) as f:
        yield f

        f.flush()
        os.fsync(f.fileno())


def _is_kaggle():
    return (
        os.getenv("KAGGLE_KERNEL_RUN_TYPE") is not None
        or "kaggle_environments" in sys.modules  # noqa: W503
    )


def split_files(files, MAX_MB=10):
    current_volume = {}
    current_size = 0
    max_size = MAX_MB * 1024 * 1024

    def _str_size(x):
        return len(x) if isinstance(x, bytes) else len(x.encode("utf-8"))

    def _file_size(file):
        size = file.get("_size")
        if size is None:
            size = sum(map(_str_size, file["content"]))
            file["_size"] = size
        return size

    def _split_file(file, num_lines):
        offset = file["offset"]
        content = file["content"]
        name = file["name"]
        f1 = {"offset": offset, "content": content[:num_lines], "name": name}
        f2 = {
            "offset": offset + num_lines,
            "content": content[num_lines:],
            "name": name,
        }
        return f1, f2

    def _num_lines_from_num_bytes(file, num_bytes):
        size = 0
        num_lines = 0
        content = file["content"]
        while num_lines < len(content):
            size += _str_size(content[num_lines])
            if size > num_bytes:
                break
            num_lines += 1
        return num_lines

    files_stack = [
        {"name": k, "offset": v["offset"], "content": v["content"]}
        for k, v in files.items()
    ]

    while files_stack:
        f = files_stack.pop()
        # For each file, we have to do 1 of 4 things:
        # - Add the file as such to the current volume if possible.
        # - Split the file and add the first part to the current volume and push the second part back onto the stack.
        # - If that's not possible, check if current volume is empty:
        # - If empty, add first line of file to current volume and push rest onto stack (This volume will exceed MAX_MB).
        # - If not, push file back to stack and yield current volume.
        fsize = _file_size(f)
        rem = max_size - current_size
        if fsize <= rem:
            current_volume[f["name"]] = {
                "offset": f["offset"],
                "content": f["content"],
            }
            current_size += fsize
        else:
            num_lines = _num_lines_from_num_bytes(f, rem)
            if not num_lines and not current_volume:
                num_lines = 1
            if num_lines:
                f1, f2 = _split_file(f, num_lines)
                current_volume[f1["name"]] = {
                    "offset": f1["offset"],
                    "content": f1["content"],
                }
                files_stack.append(f2)
                yield current_volume
                current_volume = {}
                current_size = 0
                continue
            else:
                files_stack.append(f)
                yield current_volume
                current_volume = {}
                current_size = 0
                continue
        if current_size >= max_size:
            yield current_volume
            current_volume = {}
            current_size = 0
            continue

    if current_volume:
        yield current_volume
