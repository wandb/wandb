#
"""Feature Flags Module.

This module implements a feature flag system for the wandb library to require experimental features
and notify the user when features have been deprecated.

Example:
    import wandb
    wandb.require("wandb-service@beta")
    wandb.require("incremental-artifacts@beta")
"""

from typing import Sequence, Union

import wandb
from wandb.errors import RequireError


class _Requires(object):
    """Internal feature class."""

    _features: Sequence[str]

    def __init__(self, features: Union[str, Sequence[str]]) -> None:
        self._features = (
            tuple([features]) if isinstance(features, str) else tuple(features)
        )

    def require_require(self) -> None:
        pass

    def apply(self) -> None:
        """Call require_* method for supported features."""
        last_message: str = ""
        for feature_item in self._features:
            full_feature = feature_item.split("@", 2)[0]
            feature = full_feature.split(":", 2)[0]
            func_str = "require_{}".format(feature.replace("-", "_"))
            func = getattr(self, func_str, None)
            if not func:
                last_message = "require() unsupported requirement: {}".format(feature)
                wandb.termwarn(last_message)
                continue
            func()

        if last_message:
            wandb.termerror(
                "Supported wandb.require() features can be found at: http://wandb.me/library-require"
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
