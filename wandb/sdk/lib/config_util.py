import json
import logging
import os
from typing import Any, Dict, Optional

import yaml

import wandb
from wandb.errors import Error
from wandb.util import load_yaml

from . import filesystem

logger = logging.getLogger("wandb")


class ConfigError(Error):
    pass


def dict_from_proto_list(obj_list):
    d = dict()
    for item in obj_list:
        d[item.key] = dict(desc=None, value=json.loads(item.value_json))
    return d


def dict_strip_value_dict(config_dict):
    d = dict()
    for k, v in config_dict.items():
        d[k] = v["value"]
    return d


def dict_no_value_from_proto_list(obj_list):
    d = dict()
    for item in obj_list:
        possible_dict = json.loads(item.value_json)
        if not isinstance(possible_dict, dict) or "value" not in possible_dict:
            continue
        d[item.key] = possible_dict["value"]

    return d


# TODO(jhr): these functions should go away once we merge jobspec PR
def save_config_file_from_dict(config_filename, config_dict):
    s = b"wandb_version: 1"
    if config_dict:  # adding an empty dictionary here causes a parse error
        s += b"\n\n" + yaml.dump(
            config_dict,
            Dumper=yaml.SafeDumper,
            default_flow_style=False,
            allow_unicode=True,
            encoding="utf-8",
            sort_keys=False,
        )
    data = s.decode("utf-8")
    filesystem.mkdir_exists_ok(os.path.dirname(config_filename))
    with open(config_filename, "w") as conf_file:
        conf_file.write(data)


def dict_from_config_file(
    filename: str, must_exist: bool = False
) -> Optional[Dict[str, Any]]:
    if not os.path.exists(filename):
        if must_exist:
            raise ConfigError(f"config file {filename} doesn't exist")
        logger.debug(f"no default config file found in {filename}")
        return None
    try:
        conf_file = open(filename)
    except OSError:
        raise ConfigError(f"Couldn't read config file: {filename}")
    try:
        loaded = load_yaml(conf_file)
    except yaml.parser.ParserError:
        raise ConfigError("Invalid YAML in config yaml")
    if loaded is None:
        wandb.termwarn(
            "Found an empty default config file (config-defaults.yaml). Proceeding with no defaults."
        )
        return None
    config_version = loaded.pop("wandb_version", None)
    if config_version is not None and config_version != 1:
        raise ConfigError("Unknown config version")
    data = dict()
    for k, v in loaded.items():
        data[k] = v["value"]
    return data


def merge_dicts(dest: dict, src: dict) -> dict:
    """Recursively merge two dictionaries. Similar to Lodash's _.merge()."""
    for key, value in src.items():
        if isinstance(value, dict) and key in dest and isinstance(dest[key], dict):
            merge_dicts(dest[key], value)
        else:
            dest[key] = value
    return dest
