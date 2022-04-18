import inspect
import types
from typing import Dict, List

from wandb.errors import ConfigError, UsageError

from .lib import config_util

# Nested config objects are delimited with this character
NESTED_CONFIG_DELIMITER = "."


def nest_config(params: Dict, delimiter: str = NESTED_CONFIG_DELIMITER) -> Dict:
    _flatten_dict(params, delimiter)
    return params


def unnest_config(params: Dict, delimiter: str = NESTED_CONFIG_DELIMITER) -> Dict:
    _unflatten_dict(params, delimiter)
    return params


def _flatten_dict(d: Dict, delimiter: str) -> None:
    """Flatten dict with nested keys into a single level dict with a specified delimiter.

    Based on community solution:

    https://github.com/wandb/client/issues/982#issuecomment-1014525666

    """
    if type(d) == dict:
        for k, v in list(d.items()):
            if type(v) == dict:
                _flatten_dict(v)
                d.pop(k)
                if not isinstance(k, str):
                    raise ConfigError(
                        f"Config keys must be strings, found {k} of type {type(k)}"
                    )
                for subkey, subval in v.items():
                    if not isinstance(subkey, str):
                        raise ConfigError(
                            f"Config keys must be strings, found {subkey} of type {type(subkey)}"
                        )
                    d[f"{k}{delimiter}{subkey}"] = subval


def _unflatten_dict(d: Dict, delimiter: str) -> None:
    """Un-flatten a single level dict to a nested dict with a specified delimiter.

    Based on community solution:

    https://github.com/wandb/client/issues/982#issuecomment-1014525666

    """
    if type(d) == dict:
        # The reverse sorting here ensures that "foo.bar" will appear before "foo"
        for k in sorted(d.keys(), reverse=True):
            if not isinstance(k, str):
                raise ConfigError(
                    f"Config keys must be strings, found {k} of type {type(k)}"
                )
            if delimiter in k:
                subdict: Dict = d
                subkeys: List[str] = k.split(delimiter)
                for i, subkey in enumerate(subkeys):
                    # Check to see if key is in parent level dict
                    if subkey in d and not isinstance(subdict[subkey], dict):
                        conflict_key: str = delimiter.join(subkeys[: i + 1])
                        raise ConfigError(
                            f"While un-nesting config, found key {subkey} which conflics with key {conflict_key}"
                        )
                    else:
                        # Create a nested dictionary under the parent key
                        _d: Dict = dict()
                        subdict[subkey] = _d
                        subdict = _d
                if isinstance(subdict, dict):
                    subdict[subkeys[-1]] = d.pop(k)


def parse_config(params, exclude=None, include=None):
    # TODO: Nested Configs will impact this
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
            and meta.__name__ == "tensorflow.python.platform.flags"  # noqa: W503
        )
        if is_tf_flags_module or meta.__name__ == "absl.flags":
            params = params.FLAGS
            meta = inspect.getmodule(params)

    # newer tensorflow flags (post 1.4) uses absl.flags
    if meta and meta.__name__ == "absl.flags._flagvalues":
        params = {name: params[name].value for name in dir(params)}
    elif "__flags" in vars(params):
        # for older tensorflow flags (pre 1.4)
        if not "__parsed" not in vars(params):
            params._parse_flags()
        params = vars(params)["__flags"]
    elif not hasattr(params, "__dict__"):
        raise TypeError("config must be a dict or have a __dict__ attribute.")
    else:
        # params is a Namespace object (argparse)
        # or something else
        params = vars(params)

    # assume argparse Namespace
    return params
