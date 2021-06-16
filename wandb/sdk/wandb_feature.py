#
"""Feature Flags Module

This module implements a feature flag system for the wandb library to enable experimental features
and notify the user when features have been deprecated.

Example:
    import wandb
    wandb.use_feature("wandb-service:beta")
    wandb.use_feature("incremental-artifacts:beta,newfeature")
"""

import wandb

if wandb.TYPE_CHECKING:
    from typing import List


class _Features(object):
    """Internal feature class"""

    _features: List[str]

    def __init__(self, features: str) -> None:
        self._features = features.split(",")

    def apply(self) -> None:
        """Call apply_feature method for supported features"""
        for feature_item in self._features:
            parts = feature_item.split(":", 2)
            # TODO: support version in parts[1:]
            feature = parts[0]
            func_str = "feature_{}".format(feature.replace("-", "_"))
            func = getattr(self, func_str, None)
            if not func:
                wandb.termwarn("use_feature() unsupported feature: {}".format(feature))
                continue
            func()


def use_feature(features: str, *args: str, **kwargs: str) -> None:
    """Indicate which experimental features are used by the script

    Arguments:
        features: (str) Features to enable

    Returns:
        `str` indicating any errors or None if successful
    """
    for v in args:
        wandb.termwarn("use_feature() ignoring unsupported parameter: {}".format(v))

    for k in kwargs:
        wandb.termwarn(
            "use_feature() ignoring unsupported named parameter: {}".format(k)
        )

    f = _Features(features=features)
    f.apply()
