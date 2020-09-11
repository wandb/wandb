import os

import six
from wandb.errors import Error
from wandb.lib import filesystem
from wandb.util import load_yaml
import yaml


class ConfigError(Error):  # type: ignore
    pass


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


def dict_from_config_file(config_filename):
    try:
        conf_file = open(config_filename)
    except OSError:
        raise ConfigError("Couldn't read config file: %s" % config_filename)
    try:
        loaded = load_yaml(conf_file)
    except yaml.parser.ParserError:
        raise ConfigError("Invalid YAML in config yaml")
    config_version = loaded.pop("wandb_version", None)
    if config_version != 1:
        raise ConfigError("Unknown config version")
    data = dict()
    for k, v in six.iteritems(loaded):
        data[k] = v["value"]
    return data
