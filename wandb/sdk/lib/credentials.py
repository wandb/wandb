import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests.utils

from wandb.errors import AuthenticationError

DEFAULT_WANDB_CREDENTIALS_FILE = Path(
    os.path.expanduser("~/.config/wandb/credentials.json")
)

_expires_at_fmt = "%Y-%m-%d %H:%M:%S"


def access_token(base_url: str, token_file: Path, credentials_file: Path) -> str:
    """Retrieve an access token from the credentials file.

    If no access token exists, create a new one by exchanging the identity
    token from the token file, and save it to the credentials file.

    Args:
        base_url (str): The base URL of the server
        token_file (pathlib.Path): The path to the file containing the
        identity token
        credentials_file (pathlib.Path): The path to file used to save
        temporary access tokens

    Returns:
        str: The access token
    """
    if not credentials_file.exists():
        _write_credentials_file(base_url, token_file, credentials_file)

    data = _fetch_credentials(base_url, token_file, credentials_file)
    return data["access_token"]


def _write_credentials_file(base_url: str, token_file: Path, credentials_file: Path):
    """Obtain an access token from the server and write it to the credentials file.

    Args:
        base_url (str): The base URL of the server
        token_file (pathlib.Path): The path to the file containing the
        identity token
        credentials_file (pathlib.Path): The path to file used to save
        temporary access tokens
    """
    credentials = _create_access_token(base_url, token_file)
    data = {"credentials": {base_url: credentials}}
    with open(credentials_file, "w") as file:
        json.dump(data, file, indent=4)

        # Set file permissions to be read/write by the owner only
        os.chmod(credentials_file, 0o600)


def _fetch_credentials(base_url: str, token_file: Path, credentials_file: Path) -> dict:
    """Fetch the access token from the credentials file.

    If the access token has expired, fetch a new one from the server and save it
    to the credentials file.

    Args:
        base_url (str): The base URL of the server
        token_file (pathlib.Path): The path to the file containing the
        identity token
        credentials_file (pathlib.Path): The path to file used to save
        temporary access tokens

    Returns:
        dict: The credentials including the access token.
    """
    creds = {}
    with open(credentials_file) as file:
        data = json.load(file)
        if "credentials" not in data:
            data["credentials"] = {}
        if base_url in data["credentials"]:
            creds = data["credentials"][base_url]

    expires_at = datetime.utcnow()
    if "expires_at" in creds:
        expires_at = datetime.strptime(creds["expires_at"], _expires_at_fmt)

    if expires_at <= datetime.utcnow():
        creds = _create_access_token(base_url, token_file)
        with open(credentials_file, "w") as file:
            data["credentials"][base_url] = creds
            json.dump(data, file, indent=4)

    return creds


def _create_access_token(base_url: str, token_file: Path) -> dict:
    """Exchange an identity token for an access token from the server.

    Args:
        base_url (str): The base URL of the server.
        token_file (pathlib.Path): The path to the file containing the
        identity token

    Returns:
        dict: The access token and its expiration.

    Raises:
        FileNotFoundError: If the token file is not found.
        OSError: If there is an issue reading the token file.
        AuthenticationError: If the server fails to provide an access token.
    """
    try:
        with open(token_file) as file:
            token = file.read().strip()
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Identity token file not found: {token_file}") from e
    except OSError as e:
        raise OSError(
            f"Failed to read the identity token from file: {token_file}"
        ) from e

    url = f"{base_url}/oidc/token"
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(url, data=data, headers=headers)

    if response.status_code != 200:
        raise AuthenticationError(
            f"Failed to retrieve access token: {response.status_code}, {response.text}"
        )

    resp_json = response.json()
    expires_at = datetime.utcnow() + timedelta(seconds=float(resp_json["expires_in"]))
    resp_json["expires_at"] = expires_at.strftime(_expires_at_fmt)
    del resp_json["expires_in"]

    return resp_json
