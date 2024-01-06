import inspect
import types

from wandb.errors import UsageError

from .lib import config_util


def parse_config(params, exclude=None, include=None):
    if exclude and include:
        raise UsageError("Expected at most only one of exclude or include")
    if isinstance(params, str):
        params = config_util.dict_from_config_file(params, must_exist=True)
    params = _to_dict(params)
    if include:
        params = {key: value for key, value in params.items() if key in include}
    if exclude:
        params = {key: value for key, value in params.items() if key not in exclude}
    return params


def _to_dict(params):
    if isinstance(params, dict):
        return params

    # Handle some cases where params is not a dictionary
    # by trying to convert it into a dictionary
    meta = inspect.getmodule(params)
    if meta:
        is_tf_flags_module = (
            isinstance(params, types.ModuleType)
            and meta.__name__ == "tensorflow.python.platform.flags"
        )
        if is_tf_flags_module or meta.__name__ == "absl.flags":
            params = params.FLAGS
            meta = inspect.getmodule(params)

    # newer tensorflow flags (post 1.4) uses absl.flags
    if meta and meta.__name__ == "absl.flags._flagvalues":
        params = {name: params[name].value for name in dir(params)}
    elif not hasattr(params, "__dict__"):
        raise TypeError("config must be a dict or have a __dict__ attribute.")
    elif "__flags" in vars(params):
        # for older tensorflow flags (pre 1.4)
        if not "__parsed" not in vars(params):
            params._parse_flags()
        params = vars(params)["__flags"]
    else:
        # params is a Namespace object (argparse)
        # or something else
        params = vars(params)

    # assume argparse Namespace
    return params
