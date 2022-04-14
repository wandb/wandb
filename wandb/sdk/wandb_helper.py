import inspect
import types
from typing import Mapping, Sequence

from wandb.errors import UsageError

from .lib import config_util


def parse_config(params, exclude=None, include=None):
    """
    Function to parse a params config object into a dictionary. Params can be
    a dictionary, a Tensorflow flags parameters settings, a namespace (argparse), a
    nested dictionary (DictConfig) or a string.
    """
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
    """
    Function to convert a dict-like parameters object into a proper dict.
    Params can be a dictionary, a Tensorflow flags parameters settings, a namespace
    (argparse) or a nested dictionary (DictConfig).
    """
    if isinstance(params, dict):
        return params

    if not hasattr(params, "__dict__"):
        raise TypeError("config must be a dict-like or have a __dict__ attribute.")

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
    elif isinstance(params, Mapping):
        # Cases where params is a dict of dict, a dict of config or other similar mapping type.
        params = _parse_nested_config(params)
    else:
        # params is a Namespace object (argparse)
        # or something else
        params = vars(params)

    # assume argparse Namespace
    return params


def _parse_nested_config(config_params):
    """
    Args:
        config_params (Mapping):
            The config parameters of the training to log, such as number of epoch, loss function, optimizer etc.

    Return:
        A dictionary with the unwrapped nested config.
    """
    un_nested_params = {}
    for param_name, element in config_params.items():
        un_nested_params.update(_unwrap_nested_config(param_name, element))
    return un_nested_params


def _unwrap_nested_config(parent_name, element):
    """
    Function to unwrap nested config such as {"nested": {"a_nested_dict": 1.0}}.
    Args:
        parent_name (str): The name of the previous level of a nested config. For example, in the nested config file
            '{"a_dict": {"nested_element": 1.0}}', the `parent_name` of nested_element is "a_dict".
        element (Union[int, float, str, Mapping, Sequence]): The element (value) of the nested config. For example,
            in the nested config file '{"a_dict": {"nested_element": 1.0}}', the `element` of is
            `{"a_nested_dict": 1.0}`.

    Return:
        A dictionary with the unwrapped nested config.
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
    elif isinstance(element, Sequence) and not isinstance(element, (str, bytes)):
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
