"""Feature Flags Module.

This module implements a feature flag system for the wandb library to require experimental features
and notify the user when features have been deprecated.

Example:
    import wandb
    wandb.require("wandb-service@beta")
    wandb.require("incremental-artifacts@beta")
"""

from __future__ import annotations

from typing import Iterable

import wandb
from wandb.errors import UnsupportedError


class _Requires:
    """Internal feature class."""

    _features: tuple[str, ...]

    def __init__(self, features: str | Iterable[str]) -> None:
        self._features = (
            tuple([features]) if isinstance(features, str) else tuple(features)
        )

    def require_require(self) -> None:
        pass

    def require_service(self) -> None:
        # Legacy no-op kept solely for backward compatibility:
        # some integrations (e.g. PyTorch Lightning) still call
        # `wandb.require('service')`, which routes here.
        wandb.termwarn(
            "`wandb.require('service')` is a no-op as it is now the default behavior."
        )

    def require_core(self) -> None:
        # Legacy no-op kept solely for backward compatibility:
        # many public codebases still call `wandb.require('core')`.
        wandb.termwarn(
            "`wandb.require('core')` is a no-op as it is now the default behavior."
        )

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
            raise UnsupportedError(last_message)


def require(
    requirement: str | Iterable[str] | None = None,
    experiment: str | Iterable[str] | None = None,
) -> None:
    """Indicate which experimental features are used by the script.

    This should be called before any other `wandb` functions, ideally right
    after importing `wandb`.

    Args:
        requirement: The name of a feature to require or an iterable of
            feature names.
        experiment: An alias for `requirement`.

    Raises:
        wandb.errors.UnsupportedError: If a feature name is unknown.
    """
    features = requirement or experiment
    if not features:
        return

    f = _Requires(features=features)
    f.apply()
