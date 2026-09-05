import dataclasses
import json
import threading
import unittest.mock
import urllib.parse
from collections.abc import Callable, Generator
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue

import pytest
import wandb
from hypothesis import settings

settings.register_profile(
    "ci",
    max_examples=10,
    deadline=timedelta(seconds=1),
)
settings.load_profile("ci")


@pytest.fixture
def api() -> wandb.Api:
    """A fake wandb.Api instance.

    Unit tests can't talk to a local-testcontainer, so most methods on this
    will fail unless patched.
    """
    with unittest.mock.patch("wandb.sdk.wandb_login._verify_login"):
        return wandb.Api()


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


# --------------------------------
# Fixtures for user test point
# --------------------------------


class RecordsUtil:
    def __init__(self, queue: Queue) -> None:
        self.records = []
        while not queue.empty():
            self.records.append(queue.get())

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, name: str) -> Generator:
        for record in self.records:
            yield from self.resolve_item(record, name)

    @staticmethod
    def resolve_item(obj, attr: str, sep: str = ".") -> list:
        for name in attr.split(sep):
            if not obj.HasField(name):
                return []
            obj = getattr(obj, name)
        return [obj]

    @staticmethod
    def dictify(obj, key: str = "key", value: str = "value_json") -> dict:
        return {getattr(item, key): getattr(item, value) for item in obj}

    @property
    def config(self) -> list:
        return [self.dictify(_c.update) for _c in self["config"]]

    @property
    def history(self) -> list:
        return [self.dictify(_h.item) for _h in self["history"]]

    @property
    def partial_history(self) -> list:
        return [self.dictify(_h.item) for _h in self["request.partial_history"]]

    @property
    def preempting(self) -> list:
        return list(self["preempting"])

    @property
    def summary(self) -> list:
        return list(self["summary"])

    @property
    def files(self) -> list:
        return list(self["files"])

    @property
    def metric(self):
        return list(self["metric"])


@pytest.fixture
def parse_records() -> Generator[Callable, None, None]:
    def records_parser_fn(q: Queue) -> RecordsUtil:
        return RecordsUtil(q)

    yield records_parser_fn
