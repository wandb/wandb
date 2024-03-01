from .add_parameter import add_parameter
from .config_file import ConfigFile
from .wandb_config import WandbConfigKeys

__all__ = ["ConfigFile", "WandbConfigKeys", "add_parameter"]


def set_wandb_config_inputs(include: list[str], exclude: list[str]):
    """Set the inputs for the wandb.config object."""
    raise NotImplementedError


def set_config_file_input(
    path: str, alias: str, include: list[str], exclude: list[str]
):
    """Set the inputs for the config file."""
    raise NotImplementedError
