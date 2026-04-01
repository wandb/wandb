from __future__ import annotations

__all__ = ["wandb_log", "unpatch_kfp"]

from typing import TYPE_CHECKING, Any, Callable

from .kfp_patch import patch_kfp, unpatch_kfp

if TYPE_CHECKING:
    from typing import ParamSpec, TypeVar, overload

    _P = ParamSpec("_P")
    _T = TypeVar("_T")

    @overload
    def wandb_log(func: Callable[_P, _T]) -> Callable[_P, _T]: ...

    @overload
    def wandb_log(**kwargs: Any) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...


try:
    from kfp import __version__ as _kfp_version
    from packaging.version import parse

    _KFP_V2 = parse(_kfp_version) >= parse("2.0.0")
except (ImportError, ValueError):
    _KFP_V2 = False


def wandb_log(
    func: Callable | None = None,
    **kwargs: Any,
) -> Callable:
    """Decorator that wraps a KFP component function and logs to W&B.

    Automatically detects the installed KFP version and delegates to the
    appropriate implementation:

    - kfp >= 2.0.0: logs input parameters to ``wandb.config``, output
      scalars via ``wandb.log``, and Input/Output artifacts as W&B
      Artifacts.
    - kfp < 2.0.0 (deprecated): legacy v1 logging behaviour.

    Example:
        ```python
        from kfp import dsl
        from wandb.integration.kfp import wandb_log


        @dsl.component
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b
        ```
    """
    if _KFP_V2:
        from .wandb_log_v2 import wandb_log
    else:
        from .wandb_log_v1 import wandb_log

    return wandb_log(func, **kwargs)


patch_kfp()
