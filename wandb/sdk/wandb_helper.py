#
import inspect
import types
from typing import Dict, Mapping, Sequence, Union

import six
from wandb.errors import UsageError

from .lib import config_util


def parse_config(params, exclude=None, include=None):
    if exclude and include:
        raise UsageError("Expected at most only one of exclude or include")
    if isinstance(params, six.string_types):
        params = config_util.dict_from_config_file(params, must_exist=True)
    params = _to_dict(params)
    if include:
        params = {key: value for key, value in six.iteritems(params) if key in include}
    if exclude:
        params = {
            key: value for key, value in six.iteritems(params) if key not in exclude
        }
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
        )  # noqa: W503
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
    elif isinstance(params, Mapping) or isinstance(params, Sequence):
        # Cases where params is a dict of dict, a dict of config, a sequence or other similar mapping type.
        params = _parse_nested_config(params)
    else:
        # params is a Namespace object (argparse)
        # or something else
        params = vars(params)

    # assume argparse Namespace
    return params


def _parse_nested_config(config_params: Union[Mapping, Sequence]) -> Dict:
    """
    Args:
        config_params (Union[Mapping, Sequence]):
            The config parameters of the training to log, such as number of epoch, loss function, optimizer etc.
    """
    un_nested_params = {}
    if isinstance(config_params, Mapping):
        for param_name, element in config_params.items():
            un_nested_params.update(_unwrap_nested_config(param_name, element))
    else:  # equivalent to "if isinstance(config_params, Sequence):"
        for idx, element in enumerate(config_params):
            un_nested_params.update(_unwrap_nested_config(str(idx), element))
    return un_nested_params


def _unwrap_nested_config(
    parent_name: str, element: Union[int, float, str, Mapping, Sequence]
) -> Dict:
    """
    Function to unwrap nested config such as {"nested": {"a_nested_dict": 1.0}}.
    """
    if isinstance(element, Mapping):
        # Case where the value is another dict (a nested dict)
        unwrapped_nested_params = {}
        for key, value in element.items():
            # We recursively open the element (Dict format type)
            unwrapped_nested_params.update(
                _unwrap_nested_config(f"{parent_name}.{key}", value)
            )
        return unwrapped_nested_params
    elif isinstance(element, Sequence) and not isinstance(element, str):
        # Case where the value is a list
        # Since str are sequence we negate it to be logged in the next else
        unwrapped_nested_params = {}
        for idx, value in enumerate(element):
            unwrapped_nested_params.update(
                _unwrap_nested_config(f"{parent_name}.{idx}", value)
            )
        return unwrapped_nested_params
    else:
        return {parent_name: element}
