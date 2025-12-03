from __future__ import annotations

import re

from typing_extensions import final, override

from wandb.sdk.lib import urls


@final
class HostUrl:
    """A validated and normalized W&B server URL.

    For convenient formatting, the __str__ representation is the URL itself.
    """

    def __init__(self, url: str) -> None:
        urls.validate_url(url)

        # Checks for wandb.ai.
        if re.match(r".*wandb\.ai[^\.]*$", url):
            if "api." not in url:
                # A user might guess that app.wandb.ai is the default cloud server.
                raise ValueError(
                    f"{url!r} is not a valid server address,"
                    + " did you mean https://api.wandb.ai?"
                )
            elif not url.startswith("https"):
                raise ValueError("http is not secure, please use https://api.wandb.ai")

        self._url = url.rstrip("/")

    def is_same_url(self, value: str | HostUrl, /) -> bool:
        """Compare normalized URLs.

        Returns true if the value is an equivalent HostUrl or a string
        that normalizes to this URL.
        """
        if isinstance(value, HostUrl):
            return self._url == value._url
        else:
            return self._url == value.rstrip("/")

    @property
    def url(self) -> str:
        return self._url

    @override
    def __str__(self) -> str:
        return self._url

    @override
    def __repr__(self) -> str:
        return f"HostUrl({self._url!r})"
