import base64
import binascii
import codecs
import colorsys
import contextlib
from datetime import date, datetime
import errno
import functools
import gzip
import hashlib
import importlib
from importlib import import_module
import json
import logging
import math
import numbers
import os
import pathlib
import platform
import queue
import random
import re
import shlex
import socket
import sys
from sys import getsizeof
import tarfile
import tempfile
import threading
import time
import traceback
from types import ModuleType, TracebackType
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    IO,
    List,
    Mapping,
    Optional,
    Sequence,
    TextIO,
    Tuple,
    Type,
    Union,
)
import urllib
from urllib.parse import quote

import requests
import sentry_sdk  # type: ignore
from sentry_sdk import capture_exception, capture_message
import shortuuid  # type: ignore
import wandb
from wandb.env import error_reporting_enabled, get_app_url, SENTRY_DSN
from wandb.errors import CommError, term, UsageError
import yaml

logger = logging.getLogger(__name__)
_not_importable = set()

MAX_LINE_BYTES = (10 << 20) - (100 << 10)  # imposed by back end
IS_GIT = os.path.exists(os.path.join(os.path.dirname(__file__), "..", ".git"))
RE_WINFNAMES = re.compile(r'[<>:"\\?*]')

# these match the environments for gorilla
if IS_GIT:
    SENTRY_ENV = "development"
else:
    SENTRY_ENV = "production"


PLATFORM_WINDOWS = "windows"
PLATFORM_LINUX = "linux"
PLATFORM_BSD = "bsd"
PLATFORM_DARWIN = "darwin"
PLATFORM_UNKNOWN = "unknown"


def get_platform_name() -> str:
    if sys.platform.startswith("win"):
        return PLATFORM_WINDOWS
    elif sys.platform.startswith("darwin"):
        return PLATFORM_DARWIN
    elif sys.platform.startswith("linux"):
        return PLATFORM_LINUX
    elif sys.platform.startswith(
        (
            "dragonfly",
            "freebsd",
            "netbsd",
            "openbsd",
        )
    ):
        return PLATFORM_BSD
    else:
        return PLATFORM_UNKNOWN


# TODO(sentry): This code needs to be moved, sentry shouldn't be initialized as a
# side effect of loading a module.
if error_reporting_enabled():
    default_dsn = (
        "https://a2f1d701163c42b097b9588e56b1c37e@o151352.ingest.sentry.io/5288891"
    )
    sentry_dsn = os.environ.get(SENTRY_DSN, default_dsn)
    sentry_sdk.init(
        dsn=sentry_dsn,
        release=wandb.__version__,
        default_integrations=False,
        environment=SENTRY_ENV,
    )

POW_10_BYTES = [
    ("B", 10**0),
    ("KB", 10**3),
    ("MB", 10**6),
    ("GB", 10**9),
    ("TB", 10**12),
    ("PB", 10**15),
    ("EB", 10**18),
]

POW_2_BYTES = [
    ("B", 2**0),
    ("KiB", 2**10),
    ("MiB", 2**20),
    ("GiB", 2**30),
    ("TiB", 2**40),
    ("PiB", 2**50),
    ("EiB", 2**60),
]


def sentry_message(message: str) -> None:
    if error_reporting_enabled():
        capture_message(message)


def sentry_exc(
    exc: Union[
        str,
        BaseException,
        Tuple[
            Optional[Type[BaseException]],
            Optional[BaseException],
            Optional[TracebackType],
        ],
        None,
    ],
    delay: bool = False,
) -> None:
    if error_reporting_enabled():
        if isinstance(exc, str):
            capture_exception(Exception(exc))
        else:
            capture_exception(exc)
        if delay:
            time.sleep(2)


def sentry_reraise(exc: Any) -> None:
    """Re-raise an exception after logging it to Sentry

    Use this for top-level exceptions when you want the user to see the traceback.

    Must be called from within an exception handler.
    """
    sentry_exc(exc)
    # this will messily add this "reraise" function to the stack trace
    # but hopefully it's not too bad
    raise exc.with_traceback(sys.exc_info()[2])


def sentry_set_scope(
    settings_dict: Optional[
        Union[
            "wandb.sdk.wandb_settings.Settings",
            "wandb.sdk.internal.settings_static.SettingsStatic",
        ]
    ] = None,
    process_context: Optional[str] = None,
) -> None:
    # Using GLOBAL_HUB means these tags will persist between threads.
    # Normally there is one hub per thread.

    # Tags come from two places: settings and args passed into this func.
    args = dict(locals())
    del args["settings_dict"]

    settings_tags = [
        "entity",
        "project",
        "run_id",
        "run_url",
        "sweep_url",
        "sweep_id",
        "deployment",
        "_require_service",
    ]

    s = settings_dict

    # convenience function for getting attr from settings
    def get(key: str) -> Any:
        return getattr(s, key, None)

    with sentry_sdk.hub.GLOBAL_HUB.configure_scope() as scope:
        scope.set_tag("platform", get_platform_name())

        # apply settings tags
        if s is not None:
            for tag in settings_tags:
                val = get(tag)
                if val not in [None, ""]:
                    scope.set_tag(tag, val)

            python_runtime = (
                "colab"
                if get("_colab")
                else ("jupyter" if get("_jupyter") else "python")
            )
            scope.set_tag("python_runtime", python_runtime)

            # Hack for constructing run_url and sweep_url given run_id and sweep_id
            required = ["entity", "project", "base_url"]
            params = {key: get(key) for key in required}
            if all(params.values()):
                # here we're guaranteed that entity, project, base_url all have valid values
                app_url = wandb.util.app_url(params["base_url"])
                e, p = (quote(params[k]) for k in ["entity", "project"])

                # TODO: the settings object will be updated to contain run_url and sweep_url
                # This is done by passing a settings_map in the run_start protocol buffer message
                for word in ["run", "sweep"]:
                    _url, _id = f"{word}_url", f"{word}_id"
                    if not get(_url) and get(_id):
                        scope.set_tag(_url, f"{app_url}/{e}/{p}/{word}s/{get(_id)}")

            if hasattr(s, "email"):
                scope.user = {"email": s.email}

        # apply directly passed-in tags
        for tag, value in args.items():
            if value is not None and value != "":
                scope.set_tag(tag, value)


def vendor_setup() -> Callable:
    """This enables us to use the vendor directory for packages we don't depend on
    Returns a function to call after imports are complete. Make sure to call this
    function or you will modify the user's path which is never good. The pattern should be:
    reset_path = vendor_setup()
    # do any vendor imports...
    reset_path()
    """
    original_path = [directory for directory in sys.path]

    def reset_import_path() -> None:
        sys.path = original_path

    parent_dir = os.path.abspath(os.path.dirname(__file__))
    vendor_dir = os.path.join(parent_dir, "vendor")
    vendor_packages = ("gql-0.2.0", "graphql-core-1.1")
    package_dirs = [os.path.join(vendor_dir, p) for p in vendor_packages]
    for p in [vendor_dir] + package_dirs:
        if p not in sys.path:
            sys.path.insert(1, p)

    return reset_import_path


def apple_gpu_stats_binary() -> str:
    parent_dir = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(parent_dir, "bin", "apple_gpu_stats")


def vendor_import(name: str) -> Any:
    reset_path = vendor_setup()
    module = import_module(name)
    reset_path()
    return module


def get_module(name: str, required: Optional[Union[str, bool]] = None) -> Any:
    """
    Return module or None. Absolute import is required.
    :param (str) name: Dot-separated module path. E.g., 'scipy.stats'.
    :param (str) required: A string to raise a ValueError if missing
    :return: (module|None) If import succeeds, the module will be returned.
    """
    if name not in _not_importable:
        try:
            return import_module(name)
        except Exception:
            _not_importable.add(name)
            msg = f"Error importing optional module {name}"
            if required:
                logger.exception(msg)
    if required and name in _not_importable:
        raise wandb.Error(required)


def get_optional_module(name) -> Optional["importlib.ModuleInterface"]:  # type: ignore
    return get_module(name)


np = get_module("numpy")

# TODO: Revisit these limits
VALUE_BYTES_LIMIT = 100000


def app_url(api_url: str) -> str:
    """Returns the frontend app url without a trailing slash."""
    # TODO: move me to settings
    app_url = get_app_url()
    if app_url is not None:
        return str(app_url.strip("/"))
    if "://api.wandb.test" in api_url:
        # dev mode
        return api_url.replace("://api.", "://app.").strip("/")
    elif "://api.wandb." in api_url:
        # cloud
        return api_url.replace("://api.", "://").strip("/")
    elif "://api." in api_url:
        # onprem cloud
        return api_url.replace("://api.", "://app.").strip("/")
    # wandb/local
    return api_url


def get_full_typename(o: Any) -> Any:
    """We determine types based on type names so we don't have to import
    (and therefore depend on) PyTorch, TensorFlow, etc.
    """
    instance_name = o.__class__.__module__ + "." + o.__class__.__name__
    if instance_name in ["builtins.module", "__builtin__.module"]:
        return o.__name__
    else:
        return instance_name


def get_h5_typename(o: Any) -> Any:
    typename = get_full_typename(o)
    if is_tf_tensor_typename(typename):
        return "tensorflow.Tensor"
    elif is_pytorch_tensor_typename(typename):
        return "torch.Tensor"
    else:
        return o.__class__.__module__.split(".")[0] + "." + o.__class__.__name__


def is_uri(string: str) -> bool:
    parsed_uri = urllib.parse.urlparse(string)
    return len(parsed_uri.scheme) > 0


def local_file_uri_to_path(uri: str) -> str:
    """
    Convert URI to local filesystem path.
    No-op if the uri does not have the expected scheme.
    """
    path = urllib.parse.urlparse(uri).path if uri.startswith("file:") else uri
    return urllib.request.url2pathname(path)


def get_local_path_or_none(path_or_uri: str) -> Optional[str]:
    """Check if the argument is a local path (no scheme or file:///) and return local path if true,
    None otherwise.
    """
    parsed_uri = urllib.parse.urlparse(path_or_uri)
    if (
        len(parsed_uri.scheme) == 0
        or parsed_uri.scheme == "file"
        and len(parsed_uri.netloc) == 0
    ):
        return local_file_uri_to_path(path_or_uri)
    else:
        return None


def make_tarfile(
    output_filename: str,
    source_dir: str,
    archive_name: str,
    custom_filter: Optional[Callable] = None,
) -> None:
    # Helper for filtering out modification timestamps
    def _filter_timestamps(tar_info: "tarfile.TarInfo") -> Optional["tarfile.TarInfo"]:
        tar_info.mtime = 0
        return tar_info if custom_filter is None else custom_filter(tar_info)

    descriptor, unzipped_filename = tempfile.mkstemp()
    try:
        with tarfile.open(unzipped_filename, "w") as tar:
            tar.add(source_dir, arcname=archive_name, filter=_filter_timestamps)
        # When gzipping the tar, don't include the tar's filename or modification time in the
        # zipped archive (see https://docs.python.org/3/library/gzip.html#gzip.GzipFile)
        with gzip.GzipFile(
            filename="", fileobj=open(output_filename, "wb"), mode="wb", mtime=0
        ) as gzipped_tar, open(unzipped_filename, "rb") as tar_file:
            gzipped_tar.write(tar_file.read())
    finally:
        os.close(descriptor)
        os.remove(unzipped_filename)


def _user_args_to_dict(arguments: List[str]) -> Dict[str, Union[str, bool]]:
    user_dict = dict()
    value: Union[str, bool]
    name: str
    i = 0
    while i < len(arguments):
        arg = arguments[i]
        split = arg.split("=", maxsplit=1)
        # flag arguments don't require a value -> set to True if specified
        if len(split) == 1 and (
            i + 1 >= len(arguments) or arguments[i + 1].startswith("-")
        ):
            name = split[0].lstrip("-")
            value = True
            i += 1
        elif len(split) == 1 and not arguments[i + 1].startswith("-"):
            name = split[0].lstrip("-")
            value = arguments[i + 1]
            i += 2
        elif len(split) == 2:
            name = split[0].lstrip("-")
            value = split[1]
            i += 1
        if name in user_dict:
            wandb.termerror(f"Repeated parameter: '{name}'")
            sys.exit(1)
        user_dict[name] = value
    return user_dict


def is_tf_tensor(obj: Any) -> bool:
    import tensorflow  # type: ignore

    return isinstance(obj, tensorflow.Tensor)


def is_tf_tensor_typename(typename: str) -> bool:
    return typename.startswith("tensorflow.") and (
        "Tensor" in typename or "Variable" in typename
    )


def is_tf_eager_tensor_typename(typename: str) -> bool:
    return typename.startswith("tensorflow.") and ("EagerTensor" in typename)


def is_pytorch_tensor(obj: Any) -> bool:
    import torch  # type: ignore

    return isinstance(obj, torch.Tensor)


def is_pytorch_tensor_typename(typename: str) -> bool:
    return typename.startswith("torch.") and (
        "Tensor" in typename or "Variable" in typename
    )


def is_jax_tensor_typename(typename: str) -> bool:
    return typename.startswith("jaxlib.") and "DeviceArray" in typename


def get_jax_tensor(obj: Any) -> Optional[Any]:
    import jax  # type: ignore

    return jax.device_get(obj)


def is_fastai_tensor_typename(typename: str) -> bool:
    return typename.startswith("fastai.") and ("Tensor" in typename)


def is_pandas_data_frame_typename(typename: str) -> bool:
    return typename.startswith("pandas.") and "DataFrame" in typename


def is_matplotlib_typename(typename: str) -> bool:
    return typename.startswith("matplotlib.")


def is_plotly_typename(typename: str) -> bool:
    return typename.startswith("plotly.")


def is_plotly_figure_typename(typename: str) -> bool:
    return typename.startswith("plotly.") and typename.endswith(".Figure")


def is_numpy_array(obj: Any) -> bool:
    return np and isinstance(obj, np.ndarray)


def is_pandas_data_frame(obj: Any) -> bool:
    return is_pandas_data_frame_typename(get_full_typename(obj))


def ensure_matplotlib_figure(obj: Any) -> Any:
    """Extract the current figure from a matplotlib object or return the object if it's a figure.
    raises ValueError if the object can't be converted.
    """
    import matplotlib  # type: ignore
    from matplotlib.figure import Figure  # type: ignore

    # there are combinations of plotly and matplotlib versions that don't work well together,
    # this patches matplotlib to add a removed method that plotly assumes exists
    from matplotlib.spines import Spine  # type: ignore

    def is_frame_like(self: Any) -> bool:
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
        position_type, amount = position  # type: ignore
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


def matplotlib_to_plotly(obj: Any) -> Any:
    obj = ensure_matplotlib_figure(obj)
    tools = get_module(
        "plotly.tools",
        required=(
            "plotly is required to log interactive plots, install with: "
            "`pip install plotly` or convert the plot to an image with `wandb.Image(plt)`"
        ),
    )
    return tools.mpl_to_plotly(obj)


def matplotlib_contains_images(obj: Any) -> bool:
    obj = ensure_matplotlib_figure(obj)
    return any(len(ax.images) > 0 for ax in obj.axes)


def json_friendly(  # noqa: C901
    obj: Any,
) -> Union[Tuple[Any, bool], Tuple[Union[None, str, float], bool]]:  # noqa: C901
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
            obj = obj.cpu().detach().numpy()
        else:
            return obj.item(), True
    elif is_jax_tensor_typename(typename):
        obj = get_jax_tensor(obj)

    if is_numpy_array(obj):
        if obj.size == 1:
            obj = obj.flatten()[0]
        elif obj.size <= 32:
            obj = obj.tolist()
    elif np and isinstance(obj, np.generic):
        obj = obj.item()
        if isinstance(obj, float) and math.isnan(obj):
            obj = None
        elif isinstance(obj, np.generic) and obj.dtype.kind == "f":
            # obj is a numpy float with precision greater than that of native python float
            # (i.e., float96 or float128). in this case obj.item() does not return a native
            # python float to avoid loss of precision, so we need to explicitly cast this
            # down to a 64bit float
            obj = float(obj)

    elif isinstance(obj, bytes):
        obj = obj.decode("utf-8")
    elif isinstance(obj, (datetime, date)):
        obj = obj.isoformat()
    elif callable(obj):
        obj = (
            f"{obj.__module__}.{obj.__qualname__}"
            if hasattr(obj, "__qualname__") and hasattr(obj, "__module__")
            else str(obj)
        )
    elif isinstance(obj, float) and math.isnan(obj):
        obj = None
    else:
        converted = False
    if getsizeof(obj) > VALUE_BYTES_LIMIT:
        wandb.termwarn(
            "Serializing object of type {} that is {} bytes".format(
                type(obj).__name__, getsizeof(obj)
            )
        )
    return obj, converted


def json_friendly_val(val: Any) -> Any:
    """Make any value (including dict, slice, sequence, etc) JSON friendly"""
    converted: Union[dict, list]
    if isinstance(val, dict):
        converted = {}
        for key, value in val.items():
            converted[key] = json_friendly_val(value)
        return converted
    if isinstance(val, slice):
        converted = dict(
            slice_start=val.start, slice_step=val.step, slice_stop=val.stop
        )
        return converted
    val, _ = json_friendly(val)
    if isinstance(val, Sequence) and not isinstance(val, str):
        converted = []
        for value in val:
            converted.append(json_friendly_val(value))
        return converted
    else:
        if val.__class__.__module__ not in ("builtins", "__builtin__"):
            val = str(val)
        return val


def convert_plots(obj: Any) -> Any:
    if is_matplotlib_typename(get_full_typename(obj)):
        tools = get_module(
            "plotly.tools",
            required=(
                "plotly is required to log interactive plots, install with: "
                "`pip install plotly` or convert the plot to an image with `wandb.Image(plt)`"
            ),
        )
        obj = tools.mpl_to_plotly(obj)

    if is_plotly_typename(get_full_typename(obj)):
        return {"_type": "plotly", "plot": obj.to_plotly_json()}
    else:
        return obj


def maybe_compress_history(obj: Any) -> Tuple[Any, bool]:
    if np and isinstance(obj, np.ndarray) and obj.size > 32:
        return wandb.Histogram(obj, num_bins=32).to_json(), True
    else:
        return obj, False


def maybe_compress_summary(obj: Any, h5_typename: str) -> Tuple[Any, bool]:
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


def launch_browser(attempt_launch_browser: bool = True) -> bool:
    """Decide if we should launch a browser"""
    _display_variables = ["DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"]
    _webbrowser_names_blocklist = ["www-browser", "lynx", "links", "elinks", "w3m"]

    import webbrowser

    launch_browser = attempt_launch_browser
    if launch_browser:
        if "linux" in sys.platform and not any(
            os.getenv(var) for var in _display_variables
        ):
            launch_browser = False
        try:
            browser = webbrowser.get()
            if hasattr(browser, "name") and browser.name in _webbrowser_names_blocklist:
                launch_browser = False
        except webbrowser.Error:
            launch_browser = False

    return launch_browser


def generate_id(length: int = 8) -> str:
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(alphabet=list("0123456789abcdefghijklmnopqrstuvwxyz"))
    return str(run_gen.random(length))


def parse_tfjob_config() -> Any:
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

    def default(self, obj: Any) -> Any:
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

    def default(self, obj: Any) -> Any:
        tmp_obj, converted = json_friendly(obj)
        tmp_obj, compressed = maybe_compress_summary(tmp_obj, get_h5_typename(obj))
        if converted:
            return tmp_obj
        return json.JSONEncoder.default(self, tmp_obj)


class WandBHistoryJSONEncoder(json.JSONEncoder):
    """A JSON Encoder that handles some extra types.
    This encoder turns numpy like objects with a size > 32 into histograms"""

    def default(self, obj: Any) -> Any:
        obj, converted = json_friendly(obj)
        obj, compressed = maybe_compress_history(obj)
        if converted:
            return obj
        return json.JSONEncoder.default(self, obj)


class JSONEncoderUncompressed(json.JSONEncoder):
    """A JSON Encoder that handles some extra types.
    This encoder turns numpy like objects with a size > 32 into histograms"""

    def default(self, obj: Any) -> Any:
        if is_numpy_array(obj):
            return obj.tolist()
        elif np and isinstance(obj, np.generic):
            obj = obj.item()
        return json.JSONEncoder.default(self, obj)


def json_dump_safer(obj: Any, fp: IO[str], **kwargs: Any) -> None:
    """Convert obj to json, with some extra encodable types."""
    return json.dump(obj, fp, cls=WandBJSONEncoder, **kwargs)


def json_dumps_safer(obj: Any, **kwargs: Any) -> str:
    """Convert obj to json, with some extra encodable types."""
    return json.dumps(obj, cls=WandBJSONEncoder, **kwargs)


# This is used for dumping raw json into files
def json_dump_uncompressed(obj: Any, fp: IO[str], **kwargs: Any) -> None:
    """Convert obj to json, with some extra encodable types."""
    return json.dump(obj, fp, cls=JSONEncoderUncompressed, **kwargs)


def json_dumps_safer_history(obj: Any, **kwargs: Any) -> str:
    """Convert obj to json, with some extra encodable types, including histograms"""
    return json.dumps(obj, cls=WandBHistoryJSONEncoder, **kwargs)


def make_json_if_not_number(
    v: Union[int, float, str, Mapping, Sequence]
) -> Union[int, float, str]:
    """If v is not a basic type convert it to json."""
    if isinstance(v, (float, int)):
        return v
    return json_dumps_safer(v)


def make_safe_for_json(obj: Any) -> Any:
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


def mkdir_exists_ok(path: str) -> bool:
    try:
        os.makedirs(path)
        return True
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            return False
        else:
            raise


def no_retry_auth(e: Any) -> bool:
    if hasattr(e, "exception"):
        e = e.exception
    if not isinstance(e, requests.HTTPError):
        return True
    if e.response is None:
        return True
    # Don't retry bad request errors; raise immediately
    if e.response.status_code in (400, 409):
        return False
    # Retry all non-forbidden/unauthorized/not-found errors.
    if e.response.status_code not in (401, 403, 404):
        return True
    # Crash w/message on forbidden/unauthorized errors.
    if e.response.status_code == 401:
        raise CommError("Invalid or missing api_key. Run `wandb login`")
    elif wandb.run:
        raise CommError(f"Permission denied to access {wandb.run.path}")
    else:
        raise CommError("Permission denied, ask the project owner to grant you access")


def find_runner(program: str) -> Union[None, list, List[str]]:
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
        except OSError:  # PermissionError doesn't exist in 2.7
            return None
        first_line = opened.readline().strip()
        if first_line.startswith("#!"):
            return shlex.split(first_line[2:])
        if program.endswith(".py"):
            return [sys.executable]
    return None


def downsample(values: Sequence, target_length: int) -> list:
    """Downsamples 1d values to target_length, including start and end.

    Algorithm just rounds index down.

    Values can be any sequence, including a generator.
    """
    if not target_length > 1:
        raise UsageError("target_length must be > 1")
    values = list(values)
    if len(values) < target_length:
        return values
    ratio = float(len(values) - 1) / (target_length - 1)
    result = []
    for i in range(target_length):
        result.append(values[int(i * ratio)])
    return result


def has_num(dictionary: Mapping, key: Any) -> bool:
    return key in dictionary and isinstance(dictionary[key], numbers.Number)


def md5_file(path: str) -> str:
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return base64.b64encode(hash_md5.digest()).decode("ascii")


def get_log_file_path() -> str:
    """Log file path used in error messages.

    It would probably be better if this pointed to a log file in a
    run directory.
    """
    # TODO(jhr, cvp): refactor
    if wandb.run is not None:
        return wandb.run._settings.log_internal
    return os.path.join("wandb", "debug-internal.log")


def docker_image_regex(image: str) -> Any:
    """regex for valid docker image names"""
    if image:
        return re.match(
            r"^(?:(?=[^:\/]{1,253})(?!-)[a-zA-Z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-zA-Z0-9-]{1,63}(?<!-))*(?::[0-9]{1,5})?/)?((?![._-])(?:[a-z0-9._-]*)(?<![._-])(?:/(?![._-])[a-z0-9._-]*(?<![._-]))*)(?::(?![.-])[a-zA-Z0-9_.-]{1,128})?$",
            image,
        )
    return None


def image_from_docker_args(args: List[str]) -> Optional[str]:
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
    if most_likely is None and len(possible_images) > 0:
        most_likely = possible_images[0]
    return most_likely


def load_yaml(file: Any) -> Any:
    """If pyyaml > 5.1 use full_load to avoid warning"""
    if hasattr(yaml, "full_load"):
        return yaml.full_load(file)
    else:
        return yaml.load(file)


def image_id_from_k8s() -> Optional[str]:
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
                headers={"Authorization": f"Bearer {open(token_path).read()}"},
            )
            res.raise_for_status()
        except requests.RequestException:
            return None
        try:
            return str(  # noqa: B005
                res.json()["status"]["containerStatuses"][0]["imageID"]
            ).strip("docker-pullable://")
        except (ValueError, KeyError, IndexError):
            logger.exception("Error checking kubernetes for image id")
            return None
    return None


def async_call(target: Callable, timeout: Optional[int] = None) -> Callable:
    """Accepts a method and optional timeout.
    Returns a new method that will call the original with any args, waiting for upto timeout seconds.
    This new method blocks on the original and returns the result or None
    if timeout was reached, along with the thread.
    You can check thread.is_alive() to determine if a timeout was reached.
    If an exception is thrown in the thread, we reraise it.
    """
    q: "queue.Queue" = queue.Queue()

    def wrapped_target(q: "queue.Queue", *args: Any, **kwargs: Any) -> Any:
        try:
            q.put(target(*args, **kwargs))
        except Exception as e:
            q.put(e)

    def wrapper(
        *args: Any, **kwargs: Any
    ) -> Union[Tuple[Exception, "threading.Thread"], Tuple[None, "threading.Thread"]]:
        thread = threading.Thread(
            target=wrapped_target, args=(q,) + args, kwargs=kwargs
        )
        thread.daemon = True
        thread.start()
        try:
            result = q.get(True, timeout)
            if isinstance(result, Exception):
                raise result.with_traceback(sys.exc_info()[2])
            return result, thread
        except queue.Empty:
            return None, thread

    return wrapper


def read_many_from_queue(q: "queue.Queue", max_items: int, queue_timeout: int) -> list:
    try:
        item = q.get(True, queue_timeout)
    except queue.Empty:
        return []
    items = [item]
    for _ in range(max_items):
        try:
            item = q.get_nowait()
        except queue.Empty:
            return items
        items.append(item)
    return items


def stopwatch_now() -> float:
    """Get a time value for interval comparisons

    When possible it is a monotonic clock to prevent backwards time issues.
    """
    return time.monotonic()


def class_colors(class_count: int) -> List[List[int]]:
    # make class 0 black, and the rest equally spaced fully saturated hues
    return [[0, 0, 0]] + [
        colorsys.hsv_to_rgb(i / (class_count - 1.0), 1.0, 1.0)  # type: ignore
        for i in range(class_count - 1)
    ]


def _prompt_choice(
    input_timeout: int = None,
    jupyter: bool = False,
) -> str:
    input_fn: Callable = input
    prompt = term.LOG_STRING
    if input_timeout is not None:
        # delayed import to mitigate risk of timed_input complexity
        from wandb.sdk.lib import timed_input

        input_fn = functools.partial(timed_input.timed_input, timeout=input_timeout)
        # timed_input doesnt handle enhanced prompts
        if platform.system() == "Windows":
            prompt = "wandb"

    text = f"{prompt}: Enter your choice: "
    if input_fn == input:
        choice = input_fn(text)
    else:
        choice = input_fn(text, jupyter=jupyter)
    return choice  # type: ignore


def prompt_choices(
    choices: Sequence[str],
    input_timeout: int = None,
    jupyter: bool = False,
) -> str:
    """Allow a user to choose from a list of options"""
    for i, choice in enumerate(choices):
        wandb.termlog(f"({i+1}) {choice}")

    idx = -1
    while idx < 0 or idx > len(choices) - 1:
        choice = _prompt_choice(input_timeout=input_timeout, jupyter=jupyter)
        if not choice:
            continue
        idx = -1
        try:
            idx = int(choice) - 1
        except ValueError:
            pass
        if idx < 0 or idx > len(choices) - 1:
            wandb.termwarn("Invalid choice")
    result = choices[idx]
    wandb.termlog(f"You chose '{result}'")
    return result


def guess_data_type(shape: Sequence[int], risky: bool = False) -> Optional[str]:
    """Infer the type of data based on the shape of the tensors

    Arguments:
        shape (Sequence[int]): The shape of the data
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


def download_file_from_url(
    dest_path: str, source_url: str, api_key: Optional[str] = None
) -> None:
    response = requests.get(source_url, auth=("api", api_key), stream=True, timeout=5)
    response.raise_for_status()

    if os.sep in dest_path:
        mkdir_exists_ok(os.path.dirname(dest_path))
    with fsync_open(dest_path, "wb") as file:
        for data in response.iter_content(chunk_size=1024):
            file.write(data)


def isatty(ob: IO) -> bool:
    return hasattr(ob, "isatty") and ob.isatty()


def to_human_size(size: int, units: Optional[List[Tuple[str, Any]]] = None) -> str:
    units = units or POW_10_BYTES
    unit, value = units[0]
    factor = round(float(size) / value, 1)
    return (
        f"{factor}{unit}"
        if factor < 1024 or len(units) == 1
        else to_human_size(size, units[1:])
    )


def from_human_size(size: str, units: Optional[List[Tuple[str, Any]]] = None) -> int:
    units = units or POW_10_BYTES
    units_dict = {unit.upper(): value for (unit, value) in units}
    regex = re.compile(
        r"(\d+\.?\d*)\s*({})?".format("|".join(units_dict.keys())), re.IGNORECASE
    )
    match = re.match(regex, size)
    if not match:
        raise ValueError("size must be of the form `10`, `10B` or `10 B`.")
    factor, unit = (
        float(match.group(1)),
        units_dict[match.group(2).upper()] if match.group(2) else 1,
    )
    return int(factor * unit)


def auto_project_name(program: Optional[str]) -> str:
    # if we're in git, set project name to git repo name + relative path within repo
    root_dir = wandb.wandb_sdk.lib.git.GitRepo().root_dir
    if root_dir is None:
        return "uncategorized"
    # On windows, GitRepo returns paths in unix style, but os.path is windows
    # style. Coerce here.
    root_dir = to_native_slash_path(root_dir)
    repo_name = os.path.basename(root_dir)
    if program is None:
        return str(repo_name)
    if not os.path.isabs(program):
        program = os.path.join(os.curdir, program)
    prog_dir = os.path.dirname(os.path.abspath(program))
    if not prog_dir.startswith(root_dir):
        return str(repo_name)
    project = repo_name
    sub_path = os.path.relpath(prog_dir, root_dir)
    if sub_path != ".":
        project += "-" + sub_path
    return str(project.replace(os.sep, "_"))


def parse_sweep_id(parts_dict: dict) -> Optional[str]:
    """In place parse sweep path from parts dict.

    Arguments:
        parts_dict (dict): dict(entity=,project=,name=).  Modifies dict inplace.

    Returns:
        None or str if there is an error
    """

    entity = None
    project = None
    sweep_id = parts_dict.get("name")
    if not isinstance(sweep_id, str):
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
    return None


def to_forward_slash_path(path: str) -> str:
    if platform.system() == "Windows":
        path = path.replace("\\", "/")
    return path


def to_native_slash_path(path: str) -> str:
    return path.replace("/", os.sep)


def bytes_to_hex(bytestr: Union[str, bytes]) -> str:
    return codecs.getencoder("hex")(bytestr)[0].decode("ascii")  # type: ignore


def check_and_warn_old(files: List[str]) -> bool:
    if "wandb-metadata.json" in files:
        wandb.termwarn("These runs were logged with a previous version of wandb.")
        wandb.termwarn(
            "Run pip install wandb<0.10.0 to get the old library and sync your runs."
        )
        return True
    return False


class ImportMetaHook:
    def __init__(self) -> None:
        self.modules: Dict[str, ModuleType] = dict()
        self.on_import: Dict[str, list] = dict()

    def add(self, fullname: str, on_import: Callable) -> None:
        self.on_import.setdefault(fullname, []).append(on_import)

    def install(self) -> None:
        sys.meta_path.insert(0, self)  # type: ignore

    def uninstall(self) -> None:
        sys.meta_path.remove(self)  # type: ignore

    def find_module(
        self, fullname: str, path: Optional[str] = None
    ) -> Optional["ImportMetaHook"]:
        if fullname in self.on_import:
            return self
        return None

    def load_module(self, fullname: str) -> ModuleType:
        self.uninstall()
        mod = importlib.import_module(fullname)
        self.install()
        self.modules[fullname] = mod
        on_imports = self.on_import.get(fullname)
        if on_imports:
            for f in on_imports:
                f()
        return mod

    def get_modules(self) -> Tuple[str, ...]:
        return tuple(self.modules)

    def get_module(self, module: str) -> ModuleType:
        return self.modules[module]


_import_hook: Optional[ImportMetaHook] = None


def add_import_hook(fullname: str, on_import: Callable) -> None:
    global _import_hook
    if _import_hook is None:
        _import_hook = ImportMetaHook()
        _import_hook.install()
    _import_hook.add(fullname, on_import)


def b64_to_hex_id(id_string: Any) -> str:
    return binascii.hexlify(base64.standard_b64decode(str(id_string))).decode("utf-8")


def hex_to_b64_id(encoded_string: Union[str, bytes]) -> str:
    return base64.standard_b64encode(binascii.unhexlify(encoded_string)).decode("utf-8")


def host_from_path(path: Optional[str]) -> str:
    """returns the host of the path"""
    url = urllib.parse.urlparse(path)
    return str(url.netloc)


def uri_from_path(path: Optional[str]) -> str:
    """returns the URI of the path"""
    url = urllib.parse.urlparse(path)
    uri = url.path if url.path[0] != "/" else url.path[1:]
    return str(uri)


def is_unicode_safe(stream: TextIO) -> bool:
    """returns true if the stream supports UTF-8"""
    encoding = getattr(stream, "encoding", None)
    return encoding.lower() in {"utf-8", "utf_8"} if encoding else False


def _has_internet() -> bool:
    """Attempts to open a DNS connection to Googles root servers"""
    try:
        s = socket.create_connection(("8.8.8.8", 53), 0.5)
        s.close()
        return True
    except OSError:
        return False


def rand_alphanumeric(length: int = 8, rand: Optional[ModuleType] = None) -> str:
    rand = rand or random
    return "".join(rand.choice("0123456789ABCDEF") for _ in range(length))  # type: ignore


@contextlib.contextmanager
def fsync_open(
    path: Union[pathlib.Path, str], mode: str = "w"
) -> Generator[IO[Any], None, None]:
    """
    Opens a path for I/O, guaranteeing that the file is flushed and
    fsynced when the file's context expires.
    """
    with open(path, mode) as f:
        yield f

        f.flush()
        os.fsync(f.fileno())


def _is_kaggle() -> bool:
    return (
        os.getenv("KAGGLE_KERNEL_RUN_TYPE") is not None
        or "kaggle_environments" in sys.modules  # noqa: W503
    )


def _is_likely_kaggle() -> bool:
    # Telemetry to mark first runs from Kagglers.
    return (
        _is_kaggle()
        or os.path.exists(
            os.path.expanduser(os.path.join("~", ".kaggle", "kaggle.json"))
        )
        or "kaggle" in sys.modules
    )


def _is_databricks() -> bool:
    # check if we are running inside a databricks notebook by
    # inspecting sys.modules, searching for dbutils and verifying that
    # it has the appropriate structure

    if "dbutils" in sys.modules:
        dbutils = sys.modules["dbutils"]
        if hasattr(dbutils, "shell"):
            shell = dbutils.shell  # type: ignore
            if hasattr(shell, "sc"):
                sc = shell.sc
                if hasattr(sc, "appName"):
                    return bool(sc.appName == "Databricks Shell")
    return False


def _is_py_path(path: str) -> bool:
    return path.endswith(".py")


def sweep_config_err_text_from_jsonschema_violations(violations: List[str]) -> str:
    """Consolidate violation strings from wandb/sweeps describing the ways in which a
    sweep config violates the allowed schema as a single string.

    Parameters
    ----------
    violations: list of str
        The warnings to render.

    Returns
    -------
    violation: str
        The consolidated violation text.

    """

    violation_base = (
        "Malformed sweep config detected! This may cause your sweep to behave in unexpected ways.\n"
        "To avoid this, please fix the sweep config schema violations below:"
    )

    for i, warning in enumerate(violations):
        violations[i] = f"  Violation {i + 1}. {warning}"
    violation = "\n".join([violation_base] + violations)

    return violation


def handle_sweep_config_violations(warnings: List[str]) -> None:
    """Render warnings from gorilla describing the ways in which a
    sweep config violates the allowed schema as terminal warnings.

    Parameters
    ----------
    warnings: list of str
        The warnings to render.
    """

    warning = sweep_config_err_text_from_jsonschema_violations(warnings)
    if len(warnings) > 0:
        term.termwarn(warning)


def _log_thread_stacks() -> None:
    """Log all threads, useful for debugging."""

    thread_map = {t.ident: t.name for t in threading.enumerate()}

    for thread_id, frame in sys._current_frames().items():
        logger.info(
            f"\n--- Stack for thread {thread_id} {thread_map.get(thread_id, 'unknown')} ---"
        )
        for filename, lineno, name, line in traceback.extract_stack(frame):
            logger.info(f'  File: "{filename}", line {lineno}, in {name}')
            if line:
                logger.info(f"  Line: {line}")


def check_windows_valid_filename(path: Union[int, str]) -> bool:
    return not bool(re.search(RE_WINFNAMES, path))  # type: ignore


def artifact_to_json(
    artifact: Union["wandb.sdk.wandb_artifacts.Artifact", "wandb.apis.public.Artifact"]
) -> Dict[str, Any]:
    # public.Artifact has the _sequence name, instances of wandb.Artifact
    # just have the name
    if hasattr(artifact, "_sequence_name"):
        sequence_name = artifact._sequence_name  # type: ignore
    else:
        sequence_name = artifact.name.split(":")[0]

    return {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": artifact.version,
        "sequenceName": sequence_name,
        "usedAs": artifact._use_as,
    }


def check_dict_contains_nested_artifact(d: dict, nested: bool = False) -> bool:
    for item in d.values():
        if isinstance(item, dict):
            contains_artifacts = check_dict_contains_nested_artifact(item, True)
            if contains_artifacts:
                return True
        elif (
            isinstance(item, wandb.Artifact)
            or isinstance(item, wandb.apis.public.Artifact)
            or _is_artifact_string(item)
        ) and nested:
            return True
    return False


def load_json_yaml_dict(config: str) -> Any:
    ext = os.path.splitext(config)[-1]
    if ext == ".json":
        with open(config) as f:
            return json.load(f)
    elif ext == ".yaml":
        with open(config) as f:
            return yaml.safe_load(f)
    else:
        try:
            return json.loads(config)
        except ValueError:
            return None


def _parse_entity_project_item(path: str) -> tuple:
    """Parses paths with the following formats: {item}, {project}/{item}, & {entity}/{project}/{item}.

    Args:
        path: `str`, input path; must be between 0 and 3 in length.

    Returns:
        tuple of length 3 - (item, project, entity)

    Example:
        alias, project, entity = _parse_entity_project_item("myproj/mymodel:best")

        assert entity   == ""
        assert project  == "myproj"
        assert alias    == "mymodel:best"

    """
    words = path.split("/")
    if len(words) > 3:
        raise ValueError(
            "Invalid path: must be str the form {item}, {project}/{item}, or {entity}/{project}/{item}"
        )
    padded_words = [""] * (3 - len(words)) + words
    return tuple(reversed(padded_words))


def _resolve_aliases(aliases: Optional[Union[str, List[str]]]) -> List[str]:
    """Takes in `aliases` which can be None, str, or List[str] and returns List[str].
    Ensures that "latest" is always present in the returned list.

    Args:
        aliases: `Optional[Union[str, List[str]]]`

    Returns:
        List[str], with "latest" always present.

    Example:
        aliases = _resolve_aliases(["best", "dev"])
        assert aliases == ["best", "dev", "latest"]

        aliases = _resolve_aliases("boom")
        assert aliases == ["boom", "latest"]

    """
    if aliases is None:
        aliases = []

    if not any(map(lambda x: isinstance(aliases, x), [str, list])):
        raise ValueError("`aliases` must either be None or of type str or list")

    if isinstance(aliases, str):
        aliases = [aliases]

    if "latest" not in aliases:
        aliases.append("latest")

    return aliases


def _is_artifact(v: Any) -> bool:
    return isinstance(v, wandb.Artifact) or isinstance(v, wandb.apis.public.Artifact)


def _is_artifact_string(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("wandb-artifact://")


def parse_artifact_string(v: str) -> Tuple[str, Optional[str]]:
    if not v.startswith("wandb-artifact://"):
        raise ValueError(f"Invalid artifact string: {v}")
    parsed_v = v[len("wandb-artifact://") :]
    base_uri = None
    url_info = urllib.parse.urlparse(parsed_v)
    if url_info.scheme != "":
        base_uri = f"{url_info.scheme}://{url_info.netloc}"
        parts = url_info.path.split("/")[1:]
    else:
        parts = parsed_v.split("/")
    if parts[0] == "_id":
        # for now can't fetch paths but this will be supported in the future
        # when we allow passing typed media objects, this can be extended
        # to include paths
        return parts[1], base_uri

    if len(parts) < 3:
        raise ValueError(f"Invalid artifact string: {v}")

    # for now can't fetch paths but this will be supported in the future
    # when we allow passing typed media objects, this can be extended
    # to include paths
    entity, project, name_and_alias_or_version = parts[:3]
    return f"{entity}/{project}/{name_and_alias_or_version}", base_uri


def _get_max_cli_version() -> Union[str, None]:
    max_cli_version = wandb.api.max_cli_version()
    return str(max_cli_version) if max_cli_version is not None else None


def _is_offline() -> bool:
    return (  # type: ignore[no-any-return]
        wandb.run is not None and wandb.run.settings._offline
    ) or wandb.setup().settings._offline


def ensure_text(
    string: Union[str, bytes], encoding: str = "utf-8", errors: str = "strict"
) -> str:
    """Coerce s to str."""
    if isinstance(string, bytes):
        return string.decode(encoding, errors)
    elif isinstance(string, str):
        return string
    else:
        raise TypeError(f"not expecting type '{type(string)}'")
