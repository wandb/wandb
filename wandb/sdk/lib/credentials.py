import json
import os
from datetime import datetime, timedelta
from typing import Optional

import requests.utils

from wandb.errors import AuthenticationError

DEFAULT_WANDB_CREDENTIALS_FILE = os.path.expanduser("~/.config/wandb/credentials.json")

_expires_at_fmt = "%Y-%m-%d %H:%M:%S"


def access_token(
    base_url: str, token_file: str, credentials_file: str
) -> Optional[str]:
    if not token_file:
        return None

    if not os.path.exists(credentials_file):
        write_credentials_file(base_url, token_file, credentials_file)

    data = fetch_credentials(base_url, token_file, credentials_file)
    return data["access_token"]


def write_credentials_file(base_url: str, token_file: str, credentials_file: str):
    credentials = create_access_token(base_url, token_file)
    data = {"credentials": {base_url: credentials}}
    with open(credentials_file, "w") as file:
        json.dump(data, file, indent=4)

        # Set file permissions to be read/write by the owner only
        os.chmod(credentials_file, 0o600)


def fetch_credentials(
    base_url: str, token_file: str, credentials_file: str
) -> dict:
    with open(credentials_file) as file:
        data = json.load(file)
        creds = data["credentials"][base_url]

    expires_at = datetime.utcnow()
    if creds is not None:
        expires_at = datetime.strptime(creds["expires_at"], _expires_at_fmt)

    if expires_at <= datetime.utcnow():
        creds = create_access_token(base_url, token_file)
        with open(credentials_file, "w") as file:
            data = json.load(file)
            data["credentials"][base_url] = creds
            json.dump(data, file, indent=4)

    return creds


def create_access_token(base_url: str, token_file: str) -> dict:
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
