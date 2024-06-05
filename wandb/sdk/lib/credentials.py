import json
import os
import pathlib
from datetime import datetime, timedelta
from typing import Optional

import requests.utils

from wandb.errors import AuthenticationError

DEFAULT_WANDB_CREDENTIALS_FILE = str(
    pathlib.Path("~/.config/wandb/credentials.json").expanduser()
)

_expires_at_fmt = "%Y-%m-%d %H:%M:%S"


def access_token(
    base_url: str, token_file: str, credentials_file: str
) -> Optional[str]:
    """Retrieve the access token from the credentials file or create a new one if necessary.

    Args:
        base_url (str): The base URL of the server
        token_file (str): The path to the token file.
        credentials_file (str): The path to the credentials file.

    Returns:
        Optional[str]: The access token if available, otherwise None.
    """
    if not token_file:
        return None

    if not pathlib.Path(credentials_file).exists():
        _write_credentials_file(base_url, token_file, credentials_file)

    data = _fetch_credentials(base_url, token_file, credentials_file)
    return data["access_token"]


def _write_credentials_file(base_url: str, token_file: str, credentials_file: str):
    """Write the credentials file with the access token obtained from the server.

    Args:
        base_url (str): The base URL of the server.
        token_file (str): The path to the token file.
        credentials_file (str): The path to the credentials file.
    """
    credentials = _create_access_token(base_url, token_file)
    data = {"credentials": {base_url: credentials}}
    with open(credentials_file, "w") as file:
        json.dump(data, file, indent=4)

        # Set file permissions to be read/write by the owner only
        os.chmod(credentials_file, 0o600)


def _fetch_credentials(base_url: str, token_file: str, credentials_file: str) -> dict:
    """Fetch the credentials from the credentials file. Refresh the token if it has expired.

    Args:
        base_url (str): The base URL of the server.
        token_file (str): The path to the token file.
        credentials_file (str): The path to the credentials file.

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


def _create_access_token(base_url: str, token_file: str) -> dict:
    """Create a new access token using the token file.

    Args:
        base_url (str): The base URL of the server.
        token_file (str): The path to the token file.

    Returns:
        dict: The access token and its metadata.

    Raises:
        FileNotFoundError: If the token file is not found.
        OSError: If there is an issue reading the token file.
        AuthenticationError: If the server fails to provide an access token.
    """
    try:
        with open(token_file) as file:
            token = file.read().strip()
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Token file not found: {token_file}") from e
    except OSError as e:
        raise OSError(f"Failed to read the token file: {token_file}") from e

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
