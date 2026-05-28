from __future__ import annotations

try:
    import cwsandbox
except ImportError as exc:
    raise ImportError(
        "cwsandbox is not installed. Please install it with: pip install wandb[sandbox]"
    ) from exc

from cwsandbox import *  # noqa: F403
from cwsandbox import __all__ as cwsandbox_all

# wandb specific overrides
from ._auth import _set_wandb_auth_mode
from ._secret import Secret

_set_wandb_auth_mode()

_HIDDEN = {"AuthHeaders", "set_auth_mode"}

__all__ = [name for name in cwsandbox_all if name not in _HIDDEN]
