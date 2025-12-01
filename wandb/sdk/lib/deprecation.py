from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import TypeAlias

import wandb
from wandb.sdk.lib import telemetry

if TYPE_CHECKING:
    from wandb.proto.wandb_telemetry_pb2 import Deprecated


UNSET: DoNotSet = object()
"""A temporary default value for removing formerly optional parameters.

This helps distinguish explicit None arguments from implicit None.

Usage:
    def myfunction(old_param: DoNotSet = UNSET) -> ...:
        if old_param is not UNSET:
            warn_user()
        else:
            # Set to None if checked in downstream logic,
            # since UNSET is not None.
            old_param = None
        ...

    myfunction()                # Does not warn
    myfunction(old_param=None)  # Warns
"""

DoNotSet: TypeAlias = object
"""The type of UNSET."""


def warn_and_record_deprecation(
    *,
    feature: Deprecated,
    message: str,
    run: wandb.Run | None = None,
) -> None:
    """Warn the user that a feature has been deprecated and update telemetry.

    Args:
        feature: A Deprecated protobuf message with the relevant field set to True.
        message: The deprecation warning message to display to the user.
        run: The run whose telemetry to update.
    """
    with telemetry.context(run=run or wandb.run) as tel:
        tel.deprecated.MergeFrom(feature)

    wandb.termwarn(message, repeat=False)
