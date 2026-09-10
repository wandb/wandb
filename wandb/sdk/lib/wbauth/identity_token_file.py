"""The file that stores federated identity credentials.

`wandb login sso` saves the credentials it obtains here, one entry per
account, so that logging in to one W&B server does not sign the user out
of another. wandb-core reads the file to exchange an identity token for
an access token.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import tempfile
from typing import Any

from wandb import env
from wandb.errors import AuthenticationError, term

from .host_url import HostUrl

VERSION = 1


class InvalidIdentityTokenFileError(AuthenticationError):
    """An identity token file is missing or cannot be understood."""


class AmbiguousAccountError(AuthenticationError):
    """An identity token file has several accounts for one W&B server."""


def default_path() -> pathlib.Path:
    """Returns the identity-token path in the configured W&B config directory."""
    config_dir = os.getenv(env.CONFIG_DIR, "~/.config/wandb")
    return pathlib.Path(config_dir).expanduser() / "identity_token.json"


@dataclasses.dataclass(frozen=True)
class Account:
    """Credentials and metadata needed to refresh an OIDC ID token."""

    id_token: str
    refresh_token: str
    token_endpoint: str
    client_id: str
    host: str = ""
    org: str | None = None

    @property
    def key(self) -> str:
        """The key under which the account is saved."""
        host = self.host.rstrip("/")
        return f"{host}#{self.org}" if self.org else host

    def to_json(self) -> dict[str, str]:
        """Returns the account as a JSON-serializable object."""
        contents = {
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "token_endpoint": self.token_endpoint,
            "client_id": self.client_id,
        }
        if self.host:
            contents["host"] = self.host
        if self.org:
            contents["org"] = self.org
        return contents

    @classmethod
    def from_json(cls, data: Any) -> Account:
        """Reads one account from parsed JSON.

        Raises:
            InvalidIdentityTokenFileError: If the account is malformed.
        """
        if not isinstance(data, dict):
            raise InvalidIdentityTokenFileError("Each account must be an object.")

        values: dict[str, str] = {}
        for name in (
            "id_token",
            "refresh_token",
            "token_endpoint",
            "client_id",
            "host",
            "org",
        ):
            if (value := data.get(name)) is None:
                continue
            if not isinstance(value, str):
                raise InvalidIdentityTokenFileError(
                    f"The account field {name!r} must be a string."
                )
            values[name] = value

        if not values.get("id_token"):
            raise InvalidIdentityTokenFileError("Each account must have an id_token.")

        return cls(
            id_token=values["id_token"],
            refresh_token=values.get("refresh_token", ""),
            token_endpoint=values.get("token_endpoint", ""),
            client_id=values.get("client_id", ""),
            host=values.get("host", ""),
            org=values.get("org"),
        )


@dataclasses.dataclass
class Accounts:
    """Accounts saved by `wandb login sso`.

    Bare JWT files are handled only by wandb-core because they name no W&B
    server to match here.
    """

    accounts: dict[str, Account] = dataclasses.field(default_factory=dict)

    active: str | None = None
    """The key of the account to prefer when several match a W&B server."""

    def for_host(self, host: str | HostUrl) -> Account | None:
        """Returns the account to use with a W&B server, if any."""
        if not isinstance(host, HostUrl):
            host = HostUrl(host)

        matches = {
            key: account
            for key, account in self.accounts.items()
            if account.host and host.is_same_url(account.host)
        }

        if not matches:
            return None
        if len(matches) == 1:
            return next(iter(matches.values()))
        if self.active in matches:
            return matches[self.active]

        orgs = ", ".join(sorted(account.org or "?" for account in matches.values()))
        raise AmbiguousAccountError(
            f"Several accounts are saved for {host} ({orgs}), and none of them"
            + " is selected. Run `wandb login sso` to choose one."
        )

    def add(self, account: Account) -> None:
        """Saves an account and selects it for its W&B server."""
        self.accounts[account.key] = account
        self.active = account.key

    def remove_host(self, host: str | HostUrl) -> bool:
        """Forgets every account for a W&B server, reporting whether any went.

        Accounts for other servers are left alone, so signing out of one
        does not sign the user out of the rest.
        """
        if not isinstance(host, HostUrl):
            host = HostUrl(host)

        removed = [
            key
            for key, account in self.accounts.items()
            if account.host and host.is_same_url(account.host)
        ]
        for key in removed:
            del self.accounts[key]
        if self.active in removed:
            self.active = None
        return bool(removed)

    def save(self, path: str | os.PathLike[str]) -> None:
        """Atomically writes the accounts to a user-only file."""
        resolved = pathlib.Path(path).expanduser()
        resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

        contents: dict[str, Any] = {"version": VERSION}
        if self.active:
            contents["active"] = self.active
        contents["accounts"] = {
            key: account.to_json() for key, account in self.accounts.items()
        }
        data = json.dumps(contents, indent=2)

        fd, temp_path = tempfile.mkstemp(
            dir=resolved.parent, prefix=f".{resolved.name}."
        )
        try:
            with os.fdopen(fd, "w") as file:
                file.write(data)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, resolved)
        finally:
            pathlib.Path(temp_path).unlink(missing_ok=True)


def load(path: str | os.PathLike[str]) -> Accounts:
    """Reads the accounts saved in an identity token file.

    Raises:
        InvalidIdentityTokenFileError: If the file is missing, or is not an
            identity token file written by `wandb login sso`.
    """
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except OSError as e:
        raise InvalidIdentityTokenFileError(f"Could not read {path}: {e}") from None
    except json.JSONDecodeError as e:
        raise InvalidIdentityTokenFileError(f"{path} is not valid JSON: {e}") from None

    if not isinstance(data, dict):
        raise InvalidIdentityTokenFileError(f"{path} must contain a JSON object.")

    version = data.get("version", VERSION)
    if not isinstance(version, int) or version > VERSION:
        raise InvalidIdentityTokenFileError(
            f"{path} uses file format version {version}, which this version of"
            + " wandb does not understand. Upgrade wandb to use it."
        )

    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        raise InvalidIdentityTokenFileError(f"{path} has no accounts object.")

    active = data.get("active")
    if active is not None and not isinstance(active, str):
        raise InvalidIdentityTokenFileError(f"{path} has an invalid active account.")

    try:
        parsed = {key: Account.from_json(value) for key, value in accounts.items()}
    except InvalidIdentityTokenFileError as e:
        raise InvalidIdentityTokenFileError(f"{path} is malformed. {e}") from None

    return Accounts(accounts=parsed, active=active)


def load_or_empty(path: str | os.PathLike[str]) -> Accounts:
    """Reads the accounts saved in an identity token file, tolerating problems.

    Warns and returns no accounts if the file exists but cannot be read, so
    that a login is never blocked by the credentials it is about to replace.
    """
    try:
        return load(path)
    except InvalidIdentityTokenFileError as e:
        if pathlib.Path(path).exists():
            term.termwarn(f"Replacing unreadable saved credentials. {e}")
        return Accounts()
