"""Federated identity (OIDC) regression tests for gh-11722.

wandb-core exchanges the identity token for an access token and authenticates
with it as a Bearer token, so these tests observe that traffic with a fake W&B
server instead of the local-testcontainer.
"""

import dataclasses
import json
import threading
import urllib.parse
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest
import wandb


@dataclasses.dataclass
class FederatedIdentityBackend:
    """A fake W&B server for federated identity (OIDC) tests.

    Exchanges identity tokens for access tokens at /oidc/token and serves
    a viewer at /graphql, rejecting any request that does not use the
    access token with Bearer authentication.
    """

    base_url: str
    access_token: str
    identity_token: str

    entity: str = "fed-entity"
    username: str = "fed-user"

    valid: bool = True
    """Whether to accept correctly authenticated GraphQL requests."""

    token_exchanges: int = 0
    graphql_auth_headers: list[str] = dataclasses.field(default_factory=list)


@pytest.fixture
def federated_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[FederatedIdentityBackend, None, None]:
    """Configure the environment for federated identity (gh-11722).

    Starts a fake W&B server and sets WANDB_IDENTITY_TOKEN_FILE,
    WANDB_CREDENTIALS_FILE and WANDB_BASE_URL. All wandb-core network
    traffic must use an access token obtained through the OIDC
    token-exchange flow with Bearer authentication.
    """
    backend = FederatedIdentityBackend(
        base_url="",  # Filled in after the server picks a free port.
        access_token="test-access-token",
        identity_token="eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJmZWQifQ.c2ln",
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, obj, status=200):
            payload = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()

            if self.path == "/oidc/token":
                backend.token_exchanges += 1

                # Require the exact token: surrounding whitespace (like the
                # trailing newline in the token file) must be stripped.
                params = urllib.parse.parse_qs(body)
                assertion = params.get("assertion", [""])[0]
                if assertion != backend.identity_token:
                    self._json({"error": "invalid_grant"}, status=400)
                    return

                self._json({"access_token": backend.access_token, "expires_in": 3600})
                return

            if self.path == "/graphql":
                auth = self.headers.get("Authorization", "")
                backend.graphql_auth_headers.append(auth)

                authorized = auth == f"Bearer {backend.access_token}"
                if not (authorized and backend.valid):
                    self._json(
                        {"errors": [{"message": "unauthorized"}]},
                        status=401,
                    )
                    return

                self._json({"data": {"viewer": self._viewer()}})
                return

            self.send_response(404)
            self.end_headers()

        @staticmethod
        def _viewer():
            return {
                "id": "VXNlcjox",
                "name": backend.username,
                "deletedAt": None,
                "entity": backend.entity,
                "username": backend.username,
                "email": f"{backend.username}@example.com",
                "admin": False,
                "flags": "{}",
                "teams": {"edges": []},
                "apiKeys": {"edges": []},
            }

    # The known loopback name avoids slow reverse DNS on macOS runners.
    # https://github.com/actions/runner-images/issues/14409
    with mock.patch("socket.getfqdn", return_value="localhost"):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    backend.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    token_file = tmp_path / "identity-token.jwt"
    # The trailing newline is typical of token files created with `echo`
    # or an editor and must not become part of the token.
    token_file.write_text(backend.identity_token + "\n")

    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.setenv("WANDB_IDENTITY_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("WANDB_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    monkeypatch.setenv("WANDB_BASE_URL", backend.base_url)

    try:
        yield backend
    finally:
        server.shutdown()
        server.server_close()


def test_login_verify_with_token_file(federated_identity):
    """Regression test for gh-11722: federated identity in wandb.login().

    Verification goes through wandb-core, which exchanges the identity
    token for an access token and authenticates with it as a Bearer token.
    """
    logged_in = wandb.login(verify=True)

    assert logged_in is True
    assert federated_identity.token_exchanges >= 1
    assert federated_identity.graphql_auth_headers
    assert all(
        header == f"Bearer {federated_identity.access_token}"
        for header in federated_identity.graphql_auth_headers
    )


def test_login_verify_with_token_file_rejected(federated_identity):
    federated_identity.valid = False

    with pytest.raises(wandb.errors.AuthenticationError):
        wandb.login(verify=True)


def test_initialize_api_with_federated_identity(federated_identity):
    """Regression test for gh-11722: federated identity in wandb.Api().

    With WANDB_IDENTITY_TOKEN_FILE set and no API key configured, all
    network traffic goes through wandb-core, which exchanges the identity
    token for an access token and authenticates with it as a Bearer token.
    """
    api = wandb.Api()

    assert api.api_key is None
    assert api.default_entity == federated_identity.entity
    assert api.viewer.username == federated_identity.username
    assert federated_identity.token_exchanges >= 1
    assert federated_identity.graphql_auth_headers
    assert all(
        header == f"Bearer {federated_identity.access_token}"
        for header in federated_identity.graphql_auth_headers
    )
