from typing import Optional, TYPE_CHECKING

import wandb
from wandb.proto.wandb_telemetry_pb2 import Deprecated as TelemetryDeprecated
# from wandb.proto.wandb_telemetry_pb2 import TelemetryRecord


# avoid cycle, use string type reference
if TYPE_CHECKING:
    from .. import wandb_run


def deprecate(
    field_name: str,
    warning_message: str,
    run: Optional["wandb_run.Run"] = None,
):
    """
    Warn the user that a feature has been deprecated
    and store the information about the event in telemetry.

    Args:
        field_name: The name of the feature that has been deprecated.
                    Defined in wandb/proto/wandb_telemetry.proto::Deprecated
        warning_message: The message to display to the user.
        run: The run to whose telemetry the event will be added.
    """
    _run = run or wandb.run
    with wandb.wandb_lib.telemetry.context(run=_run) as tel:
        setattr(tel.deprecated, field_name, True)
    wandb.termwarn(warning_message, repeat=False)
