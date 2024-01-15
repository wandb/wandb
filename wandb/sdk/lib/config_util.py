import json
import logging
import typing
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


def update_from_proto(config_dict, config_proto):
    for item in config_proto.update:
        key_list = item.nested_key or (item.key,)
        assert key_list, "key or nested key must be set"
        target = config_dict
        # recurse down the dictionary structure:
        for prop in key_list[:-1]:
            if not target.get(prop):
                target[prop] = {}
            target = target[prop]
        # use the last element of the key to write the leaf:
        target[key_list[-1]] = json.loads(item.value_json)
    for item in config_proto.remove:
        key_list = item.nested_key or (item.key,)
        assert key_list, "key or nested key must be set"
        target = config_dict
        # recurse down the dictionary structure:
        for prop in key_list[:-1]:
            target = target[prop]
        # use the last element of the key to write the leaf:
        del target[key_list[-1]]
        # TODO(jhr): should we delete empty parents?


def dict_add_value_dict(config_dict):
    d = dict()
    for k, v in config_dict.items():
        d[k] = dict(desc=None, value=v)
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
            raise ConfigError("config file %s doesn't exist" % filename)
        logger.debug("no default config file found in %s" % filename)
        return None
    try:
        conf_file = open(filename)
    except OSError:
        raise ConfigError("Couldn't read config file: %s" % filename)
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
    """
    Recursively merge two dictionaries. Similar to Lodash's _.merge().
    """
    for key, value in src.items():
        if isinstance(value, dict) and key in dest and isinstance(dest[key], dict):
            merge_dicts(dest[key], value)
        else:
            dest[key] = value
    return dest


def dict_differences(old_dict: dict, new_dict: dict) -> dict:
    """
    Recursively find differences between two dictionaries.
    Returns a dict representing added or modified elements in new_dict.
    """
    diff = {}
    for key, new_val in new_dict.items():
        if key not in old_dict:
            diff[key] = new_val
        elif isinstance(new_val, dict) and isinstance(old_dict.get(key), dict):
            nested_diff = dict_differences(old_dict[key], new_val)
            if nested_diff:  # Only add if there's something different
                diff[key] = nested_diff
        elif new_val != old_dict.get(key):
            diff[key] = new_val

    return diff


def have_different_values_at_same_path(dict1, dict2):
    """
    Checks if two dictionaries have different values at the same nested path.
    Returns True if a difference is found, otherwise False.
    """

    def recursive_compare(d1, d2):
        # Iterate over keys in the first dictionary
        for key in d1:
            if key in d2:
                # If both values are dictionaries, recurse
                if isinstance(d1[key], dict) and isinstance(d2[key], dict):
                    if recursive_compare(d1[key], d2[key]):
                        return True
                # If values are different, return True
                elif d1[key] != d2[key]:
                    return True

        # Iterate over keys in the second dictionary to catch any keys not in the first
        for key in d2:
            if key not in d1:
                return True

        return False

    return recursive_compare(dict1, dict2)


def find_first_leaf_path(nested_dict, current_path=[]):
    """
    Traverses a nested dictionary and returns the path to the first leaf value.
    """
    for key, value in nested_dict.items():
        # Build the current path
        new_path = current_path + [key]

        # If the value is not a dictionary, return the path
        if not isinstance(value, dict):
            return new_path

        # Otherwise, continue searching recursively
        result = find_first_leaf_path(value, new_path)
        if result is not None:
            return result

    return None


PathType = typing.Tuple[str]


class DiffDict(typing.TypedDict):
    added: typing.List[PathType]
    removed: typing.List[PathType]
    modified: typing.List[PathType]


def dict_differ(old_dict: dict, new_dict: dict, path=()) -> DiffDict:
    """
    Recursively find differences between two dictionaries.
    Returns a dict with 'added', 'removed', and 'modified' keys, using tuples for paths.
    """
    diff: DiffDict = {"added": [], "removed": [], "modified": []}

    for key in old_dict:
        if key not in new_dict:
            diff["removed"].append(path + (key,))
        elif isinstance(old_dict[key], dict) and isinstance(new_dict[key], dict):
            nested_diff = dict_differ(old_dict[key], new_dict[key], path + (key,))
            for change_type in nested_diff:
                diff[change_type].extend(nested_diff[change_type])
        elif old_dict[key] != new_dict[key]:
            diff["modified"].append(path + (key,))

    for key in new_dict:
        if key not in old_dict:
            diff["added"].append(path + (key,))

    return diff


def construct_dict_from_paths(paths):
    """
    Construct a nested dictionary from a list of tuple paths.
    Leaf nodes are represented by None.
    """
    root = {}
    for path in paths:
        current_level = root
        for part in path:
            if part == path[-1]:
                current_level[part] = None
            else:
                current_level = current_level.setdefault(part, {})
    return root
