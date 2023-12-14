__all__ = ["deprecate", "Deprecated"]

from typing import TYPE_CHECKING, Optional, Tuple

import wandb
from wandb.proto.wandb_deprecated import DEPRECATED_FEATURES, Deprecated
from wandb.proto.wandb_telemetry_pb2 import Deprecated as TelemetryDeprecated

# avoid cycle, use string type reference
if TYPE_CHECKING:
    from .. import wandb_run


deprecated_field_names: Tuple[str, ...] = tuple(
    str(v) for k, v in Deprecated.__dict__.items() if not k.startswith("_")
)


def deprecate(
    field_name: DEPRECATED_FEATURES,
    warning_message: str,
    run: Optional["wandb_run.Run"] = None,
) -> None:
    """Warn the user that a feature has been deprecated.

    Also stores the information about the event in telemetry.

    Args:
        field_name: The name of the feature that has been deprecated.
                    Defined in wandb/proto/wandb_telemetry.proto::Deprecated
        warning_message: The message to display to the user.
        run: The run to whose telemetry the event will be added.
    """
    known_fields = TelemetryDeprecated.DESCRIPTOR.fields_by_name.keys()
    if field_name not in known_fields:
        raise ValueError(
            f"Unknown field name: {field_name}. Known fields: {known_fields}"
        )
    _run = run or wandb.run
    with wandb.wandb_lib.telemetry.context(run=_run) as tel:  # type: ignore[attr-defined]
        setattr(tel.deprecated, field_name, True)
    wandb.termwarn(warning_message, repeat=False)
