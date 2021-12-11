from typing import Optional

import wandb


def deprecate(
    field_name: str,
    warning_message: str,
    run: Optional[wandb.sdk.wandb_run.Run] = None,
):
    """
    Warn the user that a feature has been deprecated
    and store the information about the event in telemetry.

    Args:
        field_name: The name of the feature that has been deprecated.
                    Defined in wandb/proto/wandb_telemetry.proto::Deprecated
        warning_message: The message to display to the user.
        run: The run, to whose telemetry the event will be added.
    """
    wandb_run = wandb.run if run is None else run
    with wandb.wandb_lib.telemetry.context(run=wandb_run) as tel:
        setattr(tel.deprecated, field_name, True)
    wandb.termwarn(warning_message, repeat=False)
