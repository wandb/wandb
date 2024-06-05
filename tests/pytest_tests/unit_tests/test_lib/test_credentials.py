from datetime import datetime, timedelta
import json
from pathlib import Path

import responses

from wandb.sdk.lib.credentials import access_token, _expires_at_fmt


def write_credentials(data: dict, credentials_file: str):
    with open(credentials_file, "w") as f:
        json.dump(data, f)


def write_token(token_file: str):
    with open(token_file, "w") as f:
        f.write("eykldfkma94wp4rm")


def test_write_credentials(tmp_path: Path):
    base_url = "http://localhost"
    token_file = str(tmp_path / "jwt.txt")
    write_token(token_file)
    credentials_file = str(tmp_path / "credentials.json")

    expected_response = {'access_token': 'wb_at_39fdjsaknasd', "expires_in": 2839023}

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            base_url + "/oidc/token",
            json=expected_response
        )

        res = access_token(base_url, token_file, credentials_file)
        assert res == expected_response["access_token"]

        with open(credentials_file) as f:
            data = json.load(f)
            creds = data["credentials"][base_url]
            assert creds["expires_at"]
            assert creds["access_token"] == expected_response["access_token"]


def test_fetch_credentials(tmp_path: Path):
    base_url = "http://localhost"
    token_file = str(tmp_path / "jwt.txt")
    credentials_file = str(tmp_path / "credentials.json")

    expires_at = datetime.now() + timedelta(days=5)
    expected = {'credentials': {base_url: {'access_token': 'wb_at_39fdjsaknasd', "expires_at": expires_at.strftime(_expires_at_fmt)}}}

    write_credentials(expected, credentials_file)
    access_token(base_url, token_file, credentials_file)


def test_refresh_credentials(tmp_path: Path):
    base_url = "http://localhost"
    token_file = str(tmp_path / "jwt.txt")
    write_token(token_file)
    credentials_file = str(tmp_path / "credentials.json")

    expires_at = datetime.now()
    old_credentials = {'credentials': {base_url: {'access_token': 'wb_at_39fdjsaknasd', "expires_at": expires_at.strftime(_expires_at_fmt)}}}
    write_credentials(old_credentials, credentials_file)

    new_credentials = {'access_token': 'wb_at_kdflfo432', "expires_in": 2839023}

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            base_url + "/oidc/token",
            json=new_credentials
        )

        res = access_token(base_url, token_file, credentials_file)
        assert res == new_credentials["access_token"]

        with open(credentials_file) as f:
            data = json.load(f)
            creds = data["credentials"][base_url]
            assert creds["expires_at"]
            assert creds["access_token"] == new_credentials["access_token"]


def test_write_credentials_other_base_url(tmp_path: Path):
    base_url = "http://localhost"
    other_base_url = "https://api.wandb.ai"
    token_file = str(tmp_path / "jwt.txt")
    write_token(token_file)
    credentials_file = str(tmp_path / "credentials.json")

    expires_at = datetime.now() + timedelta(days=5)
    other_credentials = {'credentials': {other_base_url: {'access_token': 'wb_at_39fdjsaknasd', "expires_at": expires_at.strftime(_expires_at_fmt)}}}
    write_credentials(other_credentials, credentials_file)

    new_credentials = {'access_token': 'wb_at_kdflfo432', "expires_in": 2839023}

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            base_url + "/oidc/token",
            json=new_credentials
        )

        res = access_token(base_url, token_file, credentials_file)
        assert res == new_credentials["access_token"]

        with open(credentials_file) as f:
            data = json.load(f)
            creds = data["credentials"][base_url]
            assert creds
            other_creds = data["credentials"][other_base_url]
            assert other_creds
