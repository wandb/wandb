#
import json
import logging
import os

import six
from wandb.errors import Error
from wandb.util import load_yaml
import yaml

from . import filesystem


logger = logging.getLogger("wandb")


class ConfigError(Error):  # type: ignore
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
    for k, v in six.iteritems(config_dict):
        d[k] = dict(desc=None, value=v)
    return d


def dict_strip_value_dict(config_dict):
    d = dict()
    for k, v in six.iteritems(config_dict):
        d[k] = v["value"]
    return d


def dict_no_value_from_proto_list(obj_list):
    d = dict()
    for item in obj_list:
        possible_dict = json.loads(item.value_json)
        if not isinstance(possible_dict, dict) or "value" not in possible_dict:
            # (tss) TODO: This is protecting against legacy 'wandb_version' field.
            # Should investigate why the config payload even has 'wandb_version'.
            logger.warning("key '{}' has no 'value' attribute".format(item.key))
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
        )
    data = s.decode("utf-8")
    filesystem._safe_makedirs(os.path.dirname(config_filename))
    with open(config_filename, "w") as conf_file:
        conf_file.write(data)


def dict_from_config_file(filename, must_exist=False):
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
    config_version = loaded.pop("wandb_version", None)
    if config_version is not None and config_version != 1:
        raise ConfigError("Unknown config version")
    data = dict()
    for k, v in six.iteritems(loaded):
        data[k] = v["value"]
    return data
