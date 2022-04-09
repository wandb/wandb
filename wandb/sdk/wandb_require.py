"""Feature Flags Module.

This module implements a feature flag system for the wandb library to require experimental features
and notify the user when features have been deprecated.

Example:
    import wandb
    wandb.require("wandb-service@beta")
    wandb.require("incremental-artifacts@beta")
"""

import os
from typing import Sequence, Union

import wandb
from wandb.errors import RequireError
from wandb.sdk import wandb_run
from wandb.sdk.lib.wburls import wburls


class _Requires:
    """Internal feature class."""

    _features: Sequence[str]

    def __init__(self, features: Union[str, Sequence[str]]) -> None:
        self._features = (
            tuple([features]) if isinstance(features, str) else tuple(features)
        )

    def require_require(self) -> None:
        pass

    def _require_service(self) -> None:
        os.environ["WANDB_REQUIRE_SERVICE"] = "True"
        wandb.teardown = wandb._teardown  # type: ignore
        wandb.attach = wandb._attach  # type: ignore
        wandb_run.Run.detach = wandb_run.Run._detach  # type: ignore

    def require_service(self) -> None:
        self._require_service()

    def apply(self) -> None:
        """Call require_* method for supported features."""
        last_message: str = ""
        for feature_item in self._features:
            full_feature = feature_item.split("@", 2)[0]
            feature = full_feature.split(":", 2)[0]
            func_str = "require_{}".format(feature.replace("-", "_"))
            func = getattr(self, func_str, None)
            if not func:
                last_message = f"require() unsupported requirement: {feature}"
                wandb.termwarn(last_message)
                continue
            func()

        if last_message:
            wandb.termerror(
                f"Supported wandb.require() features can be found at: {wburls.get('doc_require')}"
            )
            raise RequireError(last_message)


def require(
    requirement: Union[str, Sequence[str]] = None,
    experiment: Union[str, Sequence[str]] = None,
) -> None:
    """Indicate which experimental features are used by the script.

    Args:
        requirement: (str or list) Features to require
        experiment: (str or list) Features to require

    Raises:
        wandb.errors.RequireError: if not supported or other error
    """
    features = requirement or experiment
    if not features:
        return

    f = _Requires(features=features)
    f.apply()


def _import_module_hook() -> None:
    """On wandb import, setup anything needed based on parent process require calls."""
    # TODO: optimize by caching which pids this has been done for or use real import hooks
    # TODO: make this more generic, but for now this works
    req_service = os.environ.get("WANDB_REQUIRE_SERVICE")
    if req_service:
        require("service")
