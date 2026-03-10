try:
    from kfp import __version__ as _kfp_version
    from packaging.version import parse as _parse_version

    _KFP_V2 = _parse_version(_kfp_version) >= _parse_version("2.0.0")
except Exception:
    _KFP_V2 = False

if _KFP_V2:
    from .wandb_logging import wandb_log_v2 as wandb_log
else:
    from wandb.proto.wandb_telemetry_pb2 import Deprecated
    from wandb.sdk.lib.deprecation import warn_and_record_deprecation

    from .wandb_logging import wandb_log

    warn_and_record_deprecation(
        feature=Deprecated(kfp_v1_wandb_log=True),
        message=(
            "KFP v1 (kfp<2.0.0) support for @wandb_log is deprecated "
            "and will be removed in a future release. "
            "Please upgrade to kfp>=2.0.0."
        ),
    )

from .kfp_patch import patch_kfp, unpatch_kfp

__all__ = ["wandb_log", "unpatch_kfp"]

patch_kfp()
