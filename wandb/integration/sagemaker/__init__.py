"""wandb integration sagemaker module."""

from typing import TYPE_CHECKING

from .config import is_using_sagemaker, parse_sm_config
from .resources import parse_sm_secrets, set_global_settings, set_run_id

if TYPE_CHECKING:
    from .auth import sagemaker_auth

__all__ = [
    "sagemaker_auth",
    "is_using_sagemaker",
    "parse_sm_config",
    "parse_sm_secrets",
    "set_global_settings",
    "set_run_id",
]


def __getattr__(name: str):
    # Importing .auth pulls in the credential machinery and `requests`, which
    # is not needed for the config/resource helpers used during wandb.init().
    if name == "sagemaker_auth":
        from .auth import sagemaker_auth

        globals()[name] = sagemaker_auth
        return sagemaker_auth
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | {"sagemaker_auth"})
