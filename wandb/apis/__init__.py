"""api."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import TYPE_CHECKING, Any

import wandb
from wandb import env


def _disable_ssl() -> Callable[[], None]:
    import requests
    from urllib3.exceptions import InsecureRequestWarning

    # Because third party libraries may also use requests, we monkey patch it globally
    # and turn off urllib3 warnings instead printing a global warning to the user.
    wandb.termwarn(
        "Disabling SSL verification.  Connections to this server are not verified and may be insecure!"
    )

    requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
    old_merge_environment_settings = requests.Session.merge_environment_settings

    def merge_environment_settings(self, url, proxies, stream, verify, cert):
        settings = old_merge_environment_settings(
            self, url, proxies, stream, verify, cert
        )
        settings["verify"] = False
        return settings

    requests.Session.merge_environment_settings = merge_environment_settings

    def reset():
        requests.Session.merge_environment_settings = old_merge_environment_settings

    return reset


if env.ssl_disabled():
    _disable_ssl()


__all__ = ["Api"]

if TYPE_CHECKING:
    from .public import Api


def __getattr__(name: str) -> Any:
    # `wandb.apis.public` is imported on first use, so that `import wandb`
    # does not pay for it.
    if name in ("Api", "public"):
        public = import_module(".public", __name__)
        return public if name == "public" else public.Api
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
