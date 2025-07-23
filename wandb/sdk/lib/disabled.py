from typing import Any

from wandb.proto.wandb_deprecated import Deprecated
from wandb.sdk.lib import deprecate


class SummaryDisabled(dict):
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __getattr__(self, key):
        return self[key]

    def __getitem__(self, key):
        val = dict.__getitem__(self, key)
        if isinstance(val, dict) and not isinstance(val, SummaryDisabled):
            val = SummaryDisabled(val)
            self[key] = val
        return val


class RunDisabled:
    """Compatibility class for integrations that explicitly check for wandb.RunDisabled."""

    def __getattr__(self, name: str) -> Any:
        deprecate.deprecate(
            field_name=Deprecated.run_disabled,
            warning_message="RunDisabled is deprecated and is a no-op. "
            '`wandb.init(mode="disabled")` now returns an instance of `wandb.Run`.',
        )
