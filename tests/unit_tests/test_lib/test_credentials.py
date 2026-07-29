import http.server
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from wandb import errors
from wandb.sdk.lib.credentials import _expires_at_fmt, access_token


class _FakeOidcServer:
    """A local HTTP server standing in for the /oidc/token endpoint."""

    def __init__(self):
        self.status = 200
        self.response: dict = {}
        self.requests: list[str] = []
        """Paths of the requests received by the server."""

        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                server.requests.append(self.path)
                body = json.dumps(server.response).encode()
                self.send_response(server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def shutdown(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def oidc_server():
    server = _FakeOidcServer()
    yield server
    server.shutdown()


def write_credentials(data: dict, credentials_file: Path):
    with open(credentials_file, "w") as f:
        json.dump(data, f)


def write_token(token_file: Path):
    with open(token_file, "w") as f:
        f.write("eykldfkma94wp4rm")


def test_write_credentials(tmp_path: Path, oidc_server: _FakeOidcServer):
    base_url = oidc_server.base_url
    token_file = tmp_path / "jwt.txt"
    write_token(token_file)
    credentials_file = tmp_path / "credentials.json"

    oidc_server.response = {
        "access_token": "wb_at_39fdjsaknasd",
        "expires_in": 2839023,
    }

    res = access_token(base_url, token_file, credentials_file)
    assert res == oidc_server.response["access_token"]
    assert oidc_server.requests == ["/oidc/token"]

    with open(credentials_file) as f:
        data = json.load(f)
        creds = data["credentials"][base_url]
        assert creds["expires_at"]
        assert creds["access_token"] == oidc_server.response["access_token"]


def test_fetch_credentials(tmp_path: Path, oidc_server: _FakeOidcServer):
    base_url = oidc_server.base_url
    token_file = tmp_path / "jwt.txt"
    credentials_file = tmp_path / "credentials.json"

    expires_at = datetime.now() + timedelta(days=5)
    expected = {
        "credentials": {
            base_url: {
                "access_token": "wb_at_39fdjsaknasd",
                "expires_at": expires_at.strftime(_expires_at_fmt),
            }
        }
    }

    write_credentials(expected, credentials_file)
    access_token(base_url, token_file, credentials_file)

    assert oidc_server.requests == []


def test_refresh_credentials(tmp_path: Path, oidc_server: _FakeOidcServer):
    base_url = oidc_server.base_url
    token_file = tmp_path / "jwt.txt"
    write_token(token_file)
    credentials_file = tmp_path / "credentials.json"

    expires_at = datetime.now()
    old_credentials = {
        "credentials": {
            base_url: {
                "access_token": "wb_at_39fdjsaknasd",
                "expires_at": expires_at.strftime(_expires_at_fmt),
            }
        }
    }
    write_credentials(old_credentials, credentials_file)

    oidc_server.response = {"access_token": "wb_at_kdflfo432", "expires_in": 2839023}

    res = access_token(base_url, token_file, credentials_file)
    assert res == oidc_server.response["access_token"]

    with open(credentials_file) as f:
        data = json.load(f)
        creds = data["credentials"][base_url]
        assert creds["expires_at"]
        assert creds["access_token"] == oidc_server.response["access_token"]


def test_write_credentials_other_base_url(
    tmp_path: Path, oidc_server: _FakeOidcServer
):
    base_url = oidc_server.base_url
    other_base_url = "https://api.wandb.ai"
    token_file = tmp_path / "jwt.txt"
    write_token(token_file)
    credentials_file = tmp_path / "credentials.json"

    expires_at = datetime.now() + timedelta(days=5)
    other_credentials = {
        "credentials": {
            other_base_url: {
                "access_token": "wb_at_39fdjsaknasd",
                "expires_at": expires_at.strftime(_expires_at_fmt),
            }
        }
    }
    write_credentials(other_credentials, credentials_file)

    oidc_server.response = {"access_token": "wb_at_kdflfo432", "expires_in": 2839023}

    res = access_token(base_url, token_file, credentials_file)
    assert res == oidc_server.response["access_token"]

    with open(credentials_file) as f:
        data = json.load(f)
        creds = data["credentials"][base_url]
        assert creds
        other_creds = data["credentials"][other_base_url]
        assert other_creds


def test_token_expired(tmp_path: Path, oidc_server: _FakeOidcServer):
    base_url = oidc_server.base_url
    credentials_file = tmp_path / "credentials.json"

    token_file = tmp_path / "jwt.txt"
    write_token(token_file)

    oidc_server.status = 401
    oidc_server.response = {"error": "Token expired"}

    with pytest.raises(errors.AuthenticationError, match="Token expired"):
        access_token(base_url, token_file, credentials_file)


def test_token_file_not_found(tmp_path: Path, oidc_server: _FakeOidcServer):
    base_url = oidc_server.base_url
    token_file = tmp_path / "jwt.txt"
    credentials_file = tmp_path / "credentials.json"

    with pytest.raises(FileNotFoundError):
        access_token(base_url, token_file, credentials_file)

    assert oidc_server.requests == []
