from __future__ import annotations

__all__ = ["wandb_log", "unpatch_kfp"]

from typing import Callable

from .kfp_patch import patch_kfp, unpatch_kfp

try:
    from kfp import __version__ as _kfp_version
    from packaging.version import parse as _parse_version

    _KFP_V2 = _parse_version(_kfp_version) >= _parse_version("2.0.0")
except Exception:
    _KFP_V2 = False


def wandb_log(
    func: Callable | None = None,
    **kwargs,
) -> Callable:
    """Decorator that wraps a KFP component function and logs to W&B.

    Automatically detects the installed KFP version and delegates to the
    appropriate implementation:

    * **kfp >= 2.0.0** -- logs input parameters to ``wandb.config``, output
      scalars via ``wandb.log``, and ``Input`` / ``Output`` artifacts as W&B
      Artifacts.
    * **kfp < 2.0.0** *(deprecated)* -- legacy v1 logging behaviour.

    Usage::

        from kfp import dsl
        from wandb.integration.kfp import wandb_log


        @dsl.component
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b
    """
    if _KFP_V2:
        from .wandb_log_v2 import wandb_log as _impl
    else:
        from .wandb_log_v1 import wandb_log as _impl

    return _impl(func, **kwargs)


patch_kfp()
