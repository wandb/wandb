"""Functions for adding parameters to a run template."""

from typing import Union

from .cli_args import CliArg, CliParser
from .config_file import ConfigFile
from .wandb_config import WandbConfigKeys


def add_parameter(
    parameter: Union[CliArg, CliParser, ConfigFile, WandbConfigKeys],
):
    """Add parameter to the run template derived from this computation, if any."""
    raise NotImplementedError
