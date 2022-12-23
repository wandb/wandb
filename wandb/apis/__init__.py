"""
api.
"""

import os
from typing import Callable

import httpx
import requests
from urllib3.exceptions import InsecureRequestWarning

from wandb import env, termwarn, util


def _disable_ssl() -> Callable[[], None]:
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

    old_load_ssl_context_verify = httpx._config.SSLConfig.load_ssl_context_verify
    httpx._config.SSLConfig.load_ssl_context_verify = httpx._config.SSLConfig.load_ssl_context_no_verify

    def reset():
        requests.Session.merge_environment_settings = old_merge_environment_settings
        httpx._config.SSLConfig.load_ssl_context_verify = old_load_ssl_context_verify

    return reset


if env.ssl_disabled():
    _disable_ssl()


def _mirror_http_lib_cert_env_vars() -> Callable[[], None]:
    orig_ssl_cert_file = os.environ.get("SSL_CERT_FILE")
    orig_ssl_cert_dir = os.environ.get("SSL_CERT_DIR")
    orig_requests_ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE")

    if orig_requests_ca_bundle and os.path.exists(os.path.realpath(orig_requests_ca_bundle)):
        if os.path.isdir(os.path.realpath(orig_requests_ca_bundle)):
            os.environ["SSL_CERT_DIR"] = orig_requests_ca_bundle
        else:
            os.environ["SSL_CERT_FILE"] = orig_requests_ca_bundle
    else:
        if orig_ssl_cert_file and os.path.exists(os.path.realpath(orig_ssl_cert_file)):
            os.environ["REQUESTS_CA_BUNDLE"] = orig_ssl_cert_file
        elif orig_ssl_cert_dir and os.path.exists(os.path.realpath(orig_ssl_cert_dir)):
            os.environ["REQUESTS_CA_BUNDLE"] = orig_ssl_cert_dir

    def reset():
        for name, orig in [
            ("SSL_CERT_FILE", orig_ssl_cert_file),
            ("SSL_CERT_DIR", orig_ssl_cert_dir),
            ("REQUESTS_CA_BUNDLE", orig_requests_ca_bundle),
        ]:
            if orig is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = orig

    return reset


_mirror_http_lib_cert_env_vars()

reset_path = util.vendor_setup()

from .internal import Api as InternalApi  # noqa
from .public import Api as PublicApi  # noqa

reset_path()

__all__ = ["InternalApi", "PublicApi"]
