try:
    from kfp import __version__ as _kfp_version
    from packaging.version import parse as _parse_version

    _KFP_V2 = _parse_version(_kfp_version) >= _parse_version("2.0.0")
except (ImportError, Exception):
    _KFP_V2 = False

if _KFP_V2:
    from .wandb_logging import wandb_log_v2 as wandb_log
else:
    from .wandb_logging import wandb_log

from .kfp_patch import patch_kfp, unpatch_kfp

__all__ = ["wandb_log", "unpatch_kfp"]

patch_kfp()
