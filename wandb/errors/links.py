"""Module containing the WBURLs class and WBURL dataclass.

Used to store predefined URLs that can be associated with a name. The URLs are
shortened using with the `wandb.me` domain, using dub.co as the shortening service.
If the URLs need to be updates, use the dub.co service to point to the new URL.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WBURL:
    url: str
    description: str


class Registry:
    """A collection of URLs that can be associated with a name."""

    def __init__(self) -> None:
        self.urls: dict[str, WBURL] = {
            "wandb-launch": WBURL(
                "https://wandb.me/launch",
                "Link to the W&B launch marketing page",
            ),
            "wandb-init": WBURL(
                "https://wandb.me/wandb-init",
                "Link to the wandb.init reference documentation page",
            ),
            "define-metric": WBURL(
                "https://wandb.me/define-metric",
                "Link to the W&B developer guide documentation page on wandb.define_metric",
            ),
            "developer-guide": WBURL(
                "https://wandb.me/developer-guide",
                "Link to the W&B developer guide top level page",
            ),
            "wandb-core": WBURL(
                "https://wandb.me/wandb-core",
                "Link to the documentation for the wandb-core service",
            ),
            "wandb-server": WBURL(
                "https://wandb.me/wandb-server",
                "Link to the documentation for the self-hosted W&B server",
            ),
            "multiprocess": WBURL(
                "https://wandb.me/multiprocess",
                (
                    "Link to the W&B developer guide documentation page on how to "
                    "use wandb in a multiprocess environment"
                ),
            ),
        }

    def url(self, name: str) -> str:
        """Get the URL associated with the given name."""
        wb_url = self.urls.get(name)
        if wb_url:
            return wb_url.url
        raise ValueError(f"URL not found for {name}")

    def description(self, name: str) -> str:
        """Get the description associated with the given name."""
        wb_url = self.urls.get(name)
        if wb_url:
            return wb_url.description
        raise ValueError(f"Description not found for {name}")


# This is an instance of the Links class that can be used to access the URLs
url_registry = Registry()
