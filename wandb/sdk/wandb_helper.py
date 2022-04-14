import inspect
import types

from omegaconf import OmegaConf

from wandb.errors import UsageError
from .lib import config_util


def parse_config(params, exclude=None, include=None):
    """
    Function to parse a params config object into a dictionary. Params can be
    a dictionary, a Tensorflow flags parameters settings, a namespace (argparse),
    an OmegaConf, or a string.
    """
    if exclude and include:
        raise UsageError("Expected at most only one of exclude or include")
    if isinstance(params, str):
        params = config_util.dict_from_config_file(params, must_exist=True)
    if OmegaConf.is_config(params):
        params = _omega_conf_handling(params)
    params = _to_dict(params)
    if include:
        params = {key: value for key, value in params.items() if key in include}
    if exclude:
        params = {key: value for key, value in params.items() if key not in exclude}
    return params


def _omega_conf_handling(params):
    """
    Function to handle the conversion of OmegaConf into a true primitive dict
    container. We use the interpolations key (resolve), that is (taken from OmegaConf doc) the following:
    Given the following OmegaConf: conf = OmegaConf.create({"foo": "bar", "foo2": "${foo}"})
    When:
        OmegaConf.to_container(conf)
    Then we get the following results:
         {'foo': 'bar', 'foo2': '${foo}'}
    But when:
        OmegaConf.to_container(conf, resolve=True)
    Then we get the following results:
        {'foo': 'bar', 'foo2': 'bar'}
    """
    return OmegaConf.to_container(params, resolve=True)


def _to_dict(params):
    """
    Function to convert a dict-like parameters object into a proper dict.
    Params can be a dictionary, a Tensorflow flags parameters settings, a namespace
    (argparse) or a nested dictionary (DictConfig).
    """
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
    else:
        # params is a Namespace object (argparse)
        # or something else
        params = vars(params)

    # assume argparse Namespace
    return params
