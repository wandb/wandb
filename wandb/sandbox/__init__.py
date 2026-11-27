# ruff: noqa: E402

from __future__ import annotations

from wandb.errors.term import termwarn

termwarn(
    "`wandb.sandbox` is deprecated and will be removed in a future release. "
    "Use the `cwsandbox` package directly instead.",
    repeat=False,
)

try:
    import cwsandbox
except ImportError as exc:
    raise ImportError("cwsandbox is not installed") from exc

from cwsandbox import *  # noqa: F403
from cwsandbox import __all__ as cwsandbox_all

# wandb specific overrides
from ._auth import _set_wandb_auth_mode
from ._sandbox import Sandbox, Session
from ._secret import Secret

_set_wandb_auth_mode()

_HIDDEN = {"AuthHeaders", "set_auth_mode"}

__all__ = [name for name in cwsandbox_all if name not in _HIDDEN]
