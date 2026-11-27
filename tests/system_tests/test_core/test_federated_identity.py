"""Regression tests for https://github.com/wandb/wandb/issues/11722.

wandb-core exchanges the identity token for an access token and authenticates
with it as a Bearer token, so these tests observe that traffic with a fake W&B
server instead of the local-testcontainer.
"""

import asyncio
import dataclasses
import threading
import time
import urllib.parse
from collections.abc import Generator
from pathlib import Path

import fastapi
import fastapi.responses
import pytest
import uvicorn
import wandb


@dataclasses.dataclass
class FederatedIdentityBackend:
    """A fake W&B server for federated identity (OIDC) tests.

    Exchanges identity tokens for access tokens at /oidc/token and serves
    a viewer at /graphql, rejecting any request that does not use the
    access token with Bearer authentication.
    """

    access_token: str
    identity_token: str

    entity: str = "fed-entity"
    username: str = "fed-user"

    valid: bool = True
    """Whether to accept correctly authenticated GraphQL requests."""

    token_exchanges: int = 0
    graphql_auth_headers: list[str] = dataclasses.field(default_factory=list)

    def to_fast_api(self) -> fastapi.FastAPI:
        """Returns an ASGI app implemented by this backend."""
        app = fastapi.FastAPI()
        app.post("/oidc/token")(self._post_oidc_token)
        app.post("/graphql")(self._post_graphql)
        return app

    async def _post_oidc_token(
        self, request: fastapi.Request
    ) -> fastapi.responses.JSONResponse:
        self.token_exchanges += 1

        # Require the exact token: surrounding whitespace (like the
        # trailing newline in the token file) must be stripped.
        params = urllib.parse.parse_qs((await request.body()).decode())
        if params.get("assertion", [""])[0] != self.identity_token:
            return fastapi.responses.JSONResponse(
                {"error": "invalid_grant"},
                status_code=400,
            )

        return fastapi.responses.JSONResponse(
            {"access_token": self.access_token, "expires_in": 3600},
        )

    async def _post_graphql(
        self, request: fastapi.Request
    ) -> fastapi.responses.JSONResponse:
        auth = request.headers.get("Authorization", "")
        self.graphql_auth_headers.append(auth)

        if not (self.valid and auth == f"Bearer {self.access_token}"):
            return fastapi.responses.JSONResponse(
                {"errors": [{"message": "unauthorized"}]},
                status_code=401,
            )

        return fastapi.responses.JSONResponse(
            {
                "data": {
                    "viewer": {
                        "id": "VXNlcjox",
                        "name": self.username,
                        "deletedAt": None,
                        "entity": self.entity,
                        "username": self.username,
                        "email": f"{self.username}@example.com",
                        "admin": False,
                        "flags": "{}",
                        "teams": {"edges": []},
                        "apiKeys": {"edges": []},
                    }
                }
            },
        )


@pytest.fixture
def federated_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[FederatedIdentityBackend, None, None]:
    """Configure the environment for federated identity.

    Starts a fake W&B server and sets WANDB_IDENTITY_TOKEN_FILE,
    WANDB_CREDENTIALS_FILE and WANDB_BASE_URL. All wandb-core network
    traffic must use an access token obtained through the OIDC
    token-exchange flow with Bearer authentication.
    """
    backend = FederatedIdentityBackend(
        access_token="test-access-token",
        identity_token="eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJmZWQifQ.c2ln",
    )

    server = uvicorn.Server(
        uvicorn.Config(
            backend.to_fast_api(),
            host="127.0.0.1",
            port=0,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=asyncio.run, args=[server.serve()])
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "The fake W&B server failed to start."
        time.sleep(0.1)
    port = server.servers[0].sockets[0].getsockname()[1]

    token_file = tmp_path / "identity-token.jwt"
    # The trailing newline is typical of token files created with `echo`
    # or an editor and must not become part of the token.
    token_file.write_text(backend.identity_token + "\n")

    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.setenv("WANDB_IDENTITY_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("WANDB_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    monkeypatch.setenv("WANDB_BASE_URL", f"http://127.0.0.1:{port}")

    try:
        yield backend
    finally:
        server.should_exit = True
        thread.join(timeout=30)


def test_login_verify_with_token_file(federated_identity):
    """Verification goes through wandb-core, which exchanges the identity
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
    """With WANDB_IDENTITY_TOKEN_FILE set and no API key configured, all
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
