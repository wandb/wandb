"""Container for urls used in the wandb package.

Use this anytime a URL is displayed to the user.

Usage:
    ```python
    from wandb.sdk.lib.wburls import wburls

    print(f"This is a url {wburls.get('cli_launch')}")
    ```
"""

from typing import Dict, Optional
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from ._wburls_generated import URLS


class WBURLs:
    _urls_dict: Optional[Dict["URLS", str]]

    def __init__(self) -> None:
        self._urls_dict = None

    def _get_urls(self) -> Dict["URLS", str]:
        return dict(
            cli_launch="https://wandb.me/launch",
            doc_run="https://wandb.me/run",
            doc_require="https://wandb.me/library-require",
            doc_start_err="https://docs.wandb.ai/library/init#init-start-error",
            upgrade_local="https://wandb.me/local-upgrade",
            multiprocess="http://wandb.me/init-multiprocess",
            wandb_init="https://wandb.me/wandb-init",
        )

    def get(self, s: "URLS") -> str:
        if self._urls_dict is None:
            self._urls_dict = self._get_urls()
        return self._urls_dict[s]


wburls = WBURLs()
