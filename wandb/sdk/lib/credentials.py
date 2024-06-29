import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests.utils

from wandb.errors import AuthenticationError

DEFAULT_WANDB_CREDENTIALS_FILE = Path("~/.config/wandb/credentials.json").expanduser()

_expires_at_fmt = "%Y-%m-%d %H:%M:%S"

class Credentials:
    def __init__(self, base_url: str, token_file: Path, credentials_file: Path):
        self.base_url = base_url
        self.token_file = token_file
        self.credentials_file = credentials_file
        self.__load_credentials()

    def __load_credentials(self):
        """Retrieve an access token from the credentials file.

        If no access token exists, create a new one by exchanging the identity
        token from the token file, and save it to the credentials file.

        Args:
            base_url (str): The base URL of the server
            token_file (pathlib.Path): The path to the file containing the
            identity token
            credentials_file (pathlib.Path): The path to file used to save
            temporary access tokens
        """
        if not self.credentials_file.exists():
            self.__write_credentials_file()

        self.__token_info = self.__fetch_credentials()

    def __write_credentials_file(self):
        """Obtain an access token from the server and write it to the credentials file.

        Args:
            base_url (str): The base URL of the server
            token_file (pathlib.Path): The path to the file containing the
            identity token
            credentials_file (pathlib.Path): The path to file used to save
            temporary access tokens
        """
        credentials = self.__create_access_token()
        data = {"credentials": {self.base_url: credentials}}
        with open(self.credentials_file, "w") as file:
            json.dump(data, file, indent=4)

            # Set file permissions to be read/write by the owner only
            os.chmod(self.credentials_file, 0o600)

    def __fetch_credentials(self) -> dict:
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
        with open(self.credentials_file) as file:
            data = json.load(file)
            if "credentials" not in data:
                data["credentials"] = {}
            if self.base_url in data["credentials"]:
                creds = data["credentials"][self.base_url]

        expires_at = datetime.utcnow()
        if "expires_at" in creds:
            expires_at = datetime.strptime(creds["expires_at"], _expires_at_fmt)

        if expires_at <= datetime.utcnow():
            creds = self.__create_access_token()
            with open(self.credentials_file, "w") as file:
                data["credentials"][self.base_url] = creds
                json.dump(data, file, indent=4)

        return creds

    def __create_access_token(self) -> dict:
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
            with open(self.token_file) as file:
                token = file.read().strip()
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Identity token file not found: " f"{self.token_file}"
            ) from e
        except OSError as e:
            raise OSError(
                f"Failed to read the identity token from file: " f"{self.token_file}"
            ) from e

        url = f"{self.base_url}/oidc/token"
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
        expires_at = datetime.utcnow() + timedelta(
            seconds=float(resp_json["expires_in"])
        )
        resp_json["expires_at"] = expires_at.strftime(_expires_at_fmt)
        del resp_json["expires_in"]

        return resp_json

    def __is_token_expiring(self):
        """Check if the token is expiring within the next 5 minutes.

        Returns:
            bool: True if the token is expiring within the next 5 minutes, False otherwise.
        """
        expiration_time = datetime.strptime(
            self.__token_info["expires_at"], _expires_at_fmt
        )
        return expiration_time <= datetime.utcnow() + timedelta(minutes=5)

    @property
    def token(self):
        if self.__is_token_expiring():
            self.__load_credentials()
        return self.__token_info["access_token"]
