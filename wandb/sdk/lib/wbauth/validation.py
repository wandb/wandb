"""Validation for API keys."""

from __future__ import annotations

import pathlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi

    from .host_url import HostUrl


# Matches a JWT: three non-empty base64url segments separated by dots.
_JWT_RE = re.compile(
    r"""
    [\w-]+\.  # header
    [\w-]+\.  # payload
    [\w-]+    # signature
    """,
    re.VERBOSE,
)


def check_api_key(key: str) -> str | None:
    """Returns text describing problems with the API key, or None.

    If the key is in a valid format, returns None. Otherwise, returns
    a string formatted as a complete sentence (capitalized, punctuated)
    explaining the problem with the key.

    Args:
        key: The API key to check.
    """
    if not key:
        return "API key is empty."

    # Internal client JWTs have 3 dot-separated base64url segments
    # (header.payload.signature). They bypass legacy API key validation
    # and are sent via BasicAuth so the server can detect the JWT format.
    if _JWT_RE.fullmatch(key):
        return None

    # On-prem API keys have a variable-length prefix followed by a dash.
    #
    # NOTE: This should be rsplit(), but it is split() to be backward compatible
    # with tests that rely on that. It should be safe to change to rsplit()
    # once our tests are updated.
    parts = key.split("-", 1)
    if len(parts) == 1:
        secret = parts[0]
    else:
        _, secret = parts

    # NOTE: Dashes only allowed because of split() instead of rsplit() above.
    if not re.fullmatch(r"[\w-]+", secret):
        return "API key may only contain the letters A-Z, digits and underscores."

    if (secret_len := len(secret)) < 40:
        return f"API key must have 40+ characters, has {secret_len}."

    return None


def check_api_key_validity(
    *,
    host: HostUrl,
    api_key: str,
) -> str | None:
    """Verify that an API key is valid with the server.

    Args:
        host: The host to verify the API key with.
        api_key: The API key to verify.

    Returns:
        A string describing the problem if the API key is invalid,
        or None if it is valid.
    """
    from wandb import env
    from wandb.apis.public.service_api import ServiceApi
    from wandb.sdk import wandb_setup

    from .settings import set_auth_settings_for_api_key

    settings = wandb_setup.singleton().settings.model_copy()
    set_auth_settings_for_api_key(settings, api_key, str(host))
    service_api = ServiceApi(
        settings=settings,
        timeout=env.get_http_timeout(10),
    )

    return check_service_api_auth_validity(service_api)


def check_identity_token_validity(
    *,
    host: HostUrl,
    identity_token_file: pathlib.Path,
    credentials_file: pathlib.Path,
) -> str | None:
    """Verify that an identity token is valid with the server.

    Args:
        identity_token_file: The path to the identity token file to verify.
        host: The host to verify the identity token with.
        credentials_file: The path to the credentials file to use for authentication.

    Returns:
        A string describing the problem if the identity token is invalid,
        or None if it is valid.
    """
    from wandb import env
    from wandb.apis.public.service_api import ServiceApi
    from wandb.sdk import wandb_setup

    from .settings import set_auth_settings_for_identity_token_file

    settings = wandb_setup.singleton().settings.model_copy()
    set_auth_settings_for_identity_token_file(
        settings,
        str(identity_token_file),
        str(credentials_file),
        str(host),
    )
    service_api = ServiceApi(
        settings=settings,
        timeout=env.get_http_timeout(10),
    )

    return check_service_api_auth_validity(service_api)


def check_service_api_auth_validity(service_api: ServiceApi) -> str | None:
    """Verify the authentication with the server using pre-configured service API.

    Args:
        service_api: The pre-configured service API handle to use for authentication.

    Returns:
        A string describing the problem if the authentication is invalid,
        or None if it is valid.
    """
    from wandb.sdk.lib.service.service_connection import WandbApiFailedError

    try:
        service_api.authenticate()
    except WandbApiFailedError as e:
        return f"Failed to authenticate with {service_api.base_url}: {e}"
    except Exception as e:
        return (
            "An error occurred while checking authentication with"
            f" {service_api.base_url}: {e}"
        )

    return None
