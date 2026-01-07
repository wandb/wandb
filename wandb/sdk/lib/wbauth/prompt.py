from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit

from wandb import util
from wandb.errors import links, term

from . import saas, validation, wbnetrc
from .host_url import HostUrl

_logger = logging.getLogger(__name__)

_LOGIN_CHOICE_NEW = "Create a W&B account"
_LOGIN_CHOICE_EXISTS = "Use an existing W&B account"
_LOGIN_CHOICE_OFFLINE = "Don't visualize my results"
_LOGIN_CHOICES = [
    _LOGIN_CHOICE_NEW,
    _LOGIN_CHOICE_EXISTS,
    _LOGIN_CHOICE_OFFLINE,
]


def prompt_and_save_api_key(
    *,
    host: str | HostUrl,
    no_offline: bool = False,
    no_create: bool = False,
    referrer: str = "",
    input_timeout: float | None = None,
) -> str | None:
    """Prompt for an API key and save it to the .netrc file.

    Args:
        host: The URL to the W&B server, like 'https://api.wandb.ai'.
        no_offline: If true, do not show an option to skip logging in.
        no_create: If true, do not show an option to create a new account.
        referrer: A referrer string to tack on as a query parameter to
            the printed URL for analytics.
        input_timeout: How long to wait for user input before timing out.

    Returns:
        Either the resulting API key or None if the user selected offline mode.

    Raises:
        NotATerminalError: If a terminal is not available.
        TimeoutError: If the specified timeout expired.
    """
    if not isinstance(host, HostUrl):
        host = HostUrl(host)

    api_key = _prompt_api_key(
        host=host,
        no_offline=no_offline,
        no_create=no_create,
        referrer=referrer,
        input_timeout=input_timeout,
    )

    if not api_key:
        return None

    wbnetrc.write_netrc_auth(host=host.url, api_key=api_key)

    return api_key


def _prompt_api_key(
    *,
    host: HostUrl,
    no_offline: bool = False,
    no_create: bool = False,
    referrer: str = "",
    input_timeout: float | None = None,
) -> str | None:
    """Prompt for an API key without saving it to .netrc.

    Arguments are the same as for prompt_and_save_api_key().
    """
    if not term.can_use_terminput():
        raise term.NotATerminalError

    choices = list(_LOGIN_CHOICES)
    if no_offline:
        choices.remove(_LOGIN_CHOICE_OFFLINE)
    if no_create:
        choices.remove(_LOGIN_CHOICE_NEW)

    while True:
        choice = util.prompt_choices(choices, input_timeout=input_timeout)

        if choice == _LOGIN_CHOICE_NEW:
            key = _create_new_account(host=host, referrer=referrer)
            if problems := validation.check_api_key(key):
                term.termerror(f"Invalid API key: {problems}")
            else:
                return key

        elif choice == _LOGIN_CHOICE_EXISTS:
            key = _use_existing_account(host=host, referrer=referrer)
            if problems := validation.check_api_key(key):
                term.termerror(f"Invalid API key: {problems}")
            else:
                return key

        elif choice == _LOGIN_CHOICE_OFFLINE:
            return None

        else:
            term.termerror("Not implemented. Please select another choice.")


def _use_existing_account(host: HostUrl, referrer: str) -> str:
    """Prompt the user to paste an API key from an existing W&B account.

    Args:
        host: The W&B server URL.
        referrer: The referrer to add to the printed URL, if any.

    Returns:
        The API key entered by the user.
    """
    if saas.is_wandb_domain(host.url):
        help_url = links.url_registry.url("wandb-server")
        term.termlog(
            f"Logging into {host}. "
            + f"(Learn how to deploy a W&B server locally: {help_url})"
        )

    auth_url = _authorize_url(host, signup=False, referrer=referrer)
    term.termlog(f"Find your API key here: {auth_url}")
    return term.terminput(
        "Paste an API key from your profile and hit enter: ",
        hide=True,
    )


def _create_new_account(host: HostUrl, referrer: str) -> str:
    """Prompt the user to create a new W&B account.

    Args:
        host: The W&B server URL.
        referrer: The referrer to add to the printed URL, if any.

    Returns:
        The API key entered by the user.
    """
    url = _authorize_url(host, signup=True, referrer=referrer)
    term.termlog(f"Create an account here: {url}")
    return term.terminput(
        "Paste an API key from your profile and hit enter: ",
        hide=True,
    )


def _authorize_url(host: HostUrl, *, signup: bool, referrer: str) -> str:
    """Returns the URL for the web page showing the user's API key.

    Args:
        host: The W&B server URL.
        signup: If true, shows a signup page.
        referrer: The referrer to add to the URL, if any.
    """
    scheme, netloc, *_ = urlsplit(host.app_url, scheme="https")

    query_parts: list[str] = []
    if signup:
        query_parts.append("signup=true")
    if referrer:
        query_parts.append(f"ref={referrer}")
    query = "&".join(query_parts)

    return urlunsplit((scheme, netloc, "authorize", query, ""))
