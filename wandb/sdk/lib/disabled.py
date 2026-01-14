from typing import Any


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
        from wandb.proto.wandb_telemetry_pb2 import Deprecated
        from wandb.sdk.lib.deprecation import warn_and_record_deprecation

        warn_and_record_deprecation(
            feature=Deprecated(run_disabled=True),
            message="RunDisabled is deprecated and is a no-op. "
            '`wandb.init(mode="disabled")` now returns an instance of `wandb.Run`.',
        )
