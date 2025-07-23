from __future__ import annotations

import wandb
from wandb.proto.wandb_deprecated import DEPRECATED_FEATURES
from wandb.sdk.lib import telemetry


def deprecate(
    field_name: DEPRECATED_FEATURES,
    warning_message: str,
    run: wandb.Run | None = None,
) -> None:
    """Warn the user that a feature has been deprecated.

    If a run is provided, the given field on its telemetry is updated.
    Otherwise, the global run is used.

    Args:
        field_name: The field on the Deprecated proto for this deprecation.
        warning_message: The message to display to the user.
        run: The run whose telemetry to update.
    """
    _run = run or wandb.run
    with telemetry.context(run=_run) as tel:
        setattr(tel.deprecated, field_name, True)

    wandb.termwarn(warning_message, repeat=False)
