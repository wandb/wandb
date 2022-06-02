"""
api.
"""

import requests
from urllib3.exceptions import InsecureRequestWarning
from wandb import env
from wandb import termwarn
from wandb import util

if env.ssl_disabled():
    # Because third party libraries may also use requests, we monkey patch it globally
    # and turn off urllib3 warnings instead printing a global warning to the user.
    termwarn(
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

reset_path = util.vendor_setup()

from .internal import Api as InternalApi  # noqa
from .public import Api as PublicApi  # noqa

reset_path()

__all__ = ["InternalApi", "PublicApi"]
