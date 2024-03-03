import authlib
from contextlib import closing
import json
import logging
import os
from authlib.integrations.requests_client import OAuth2Session
import sqlite3
import time
import urllib
import webbrowser

import wandb
from wandb import env

logger = logging.getLogger(__name__)

PROVIDERS = {
    "github": {
        "device_authorization_endpoint": "https://github.com/login/device/code",
        "token_endpoint": "https://github.com/login/oauth/access_token",
        "client_id": "a441f6c00b77c46f36b4",
        "scopes": ["repo", "gist"],
    },
    "wandb": {
        "device_authorization_endpoint": "https://wandb.auth0.com/oauth/device/code",
        "token_endpoint": "https://wandb.auth0.com/oauth/token",
        "client_id": "0eVXWcQfxyjVvAYTVP0XtMzcAcB9DJue",
        "scopes": ["openid", "offline_access"],
    },
}


class WandbClient(object):
    def __init__(self):
        self._session = OAuth2Session(token_endpoint_auth_method="private_key_jwt")

    def get(self, url, **kwargs):


class OIDCManager(object):
    """
    A class for obtaining OIDC credentials
    """

    GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

    def __init__(
        self, provider: str = "github", scopes=None, client_id=None, client_secret=None
    ):
        self._token_store = TokenStore()
        self._provider = None
        self._url = None
        self._device_code = None
        self._interval = 5
        self._client_secret = client_secret
        if provider.startswith("http"):
            self._load_oidc(provider)
            self._client_id = client_id
        else:
            self._provider = PROVIDERS[provider]
            self._client_id = self._provider["client_id"]
        self.scopes = scopes or self._provider.get("scopes")

    @property
    def token(self):
        return self._token_store.token(self.host, self.client_id)

    @property
    def client_id(self):
        return self._client_id

    @property
    def authorized(self):
        token = self.token or {}
        return token.get("access_token") is not None

    @property
    def token_url(self):
        return self._provider["token_endpoint"]

    @property
    def device_url(self):
        return self._provider["device_authorization_endpoint"]

    @property
    def url(self):
        return self._url

    @property
    def host(self):
        return urllib.parse.urlparse(self.token_url).netloc

    def refresh(self):
        pass  # TODO

    def get_device_code(self, attempt_launch_browser=False):
        print(" ".join(self.scopes))
        res = requests.post(
            self.device_url,
            data={"client_id": self._client_id, "scope": " ".join(self.scopes)},
            headers={"Accept": "application/json"},
        )
        res.raise_for_status()
        device_flow = res.json()
        url = device_flow.get(
            "verification_uri_complete",
            device_flow.get("verification_uri", device_flow.get("verification_url")),
        )
        if url is None:
            raise ValueError(
                "Couldn't find url in device response: {}".format(device_flow)
            )
        self._url = url
        self._expires_at = time.time() + device_flow["expires_in"]
        self._device_code = device_flow["device_code"]
        if device_flow.get("interval"):
            self._interval = device_flow["interval"]

        if wandb.util.launch_browser(attempt_launch_browser):
            webbrowser.open(url, new=1, autoraise=True)
        return device_flow["user_code"]

    def get_token(self, timeout=None):
        if timeout is not None:
            self._expires_at = min(time.time() + timeout, self._expires_at)
        while True:
            body = {
                "client_id": self._client_id,
                "device_code": self._device_code,
                "grant_type": self.GRANT_TYPE,
            }
            # Google requires a client secret
            if self._client_secret:
                body["client_secret"] = self._client_secret
            res = requests.post(
                self.token_url, data=body, headers={"Accept": "application/json"}
            )
            # TODO: handle cancelation
            logger.info("OIDC device polling status: {}".format(res.json()))
            if res.status_code != 200:
                if time.time() > self._expires_at:
                    wandb.termwarn("Authentication timed out, please try again.")
                    break
            else:
                payload = res.json()
                if payload.get("access_token") is not None:
                    self.token_saver(payload)
                    wandb.termlog("Authentication successful!")
                    break
            time.sleep(self._interval)
        return self.token is not None

    def _load_oidc(self, discovery_url):
        """
        Loads an OIDC discovery url and gets the token_endpoint and device_authorization_endpoint keys
        Raises:
            ValueError - if the OIDC server doesn't support device authorization
        """
        try:
            res = requests.get(discovery_url)
            res.raise_for_status()
            self._provider = res.json()
            if self._provider.get("token_endpoint") is None:
                raise ValueError(
                    "OIDC discovery url does not look valid, couldn't find token_endpoint"
                )
            if self._provider.get("device_authorization_endpoint") is None:
                raise ValueError(
                    "OIDC server does not support RFC 8628 Device Authorization Grant"
                )
        except (requests.RequestException, ValueError) as e:
            wandb.termwarn("Unable to load OIDC discovery url: {}".format(e))

    def token_saver(self, token):
        return self._token_store.save(token, self.host, self.client_id)


class TokenStore(object):
    """Credential helper for atomically storing oidc tokens"""

    SCHEMA = [
        """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        migrated_at INTEGER
    )
    """,
        """
    CREATE TABLE IF NOT EXISTS tokens (
        host TEXT,
        client_id TEXT,
        token TEXT,
        expiration INTEGER,
        PRIMARY KEY(host, client_id)
    )""",
    ]

    def __init__(self):
        self.ensure_migrated()

    def ensure_migrated(self):
        statements = self.SCHEMA[self.version :]
        if len(statements) > 0:
            for stmt in statements:
                self.execute(stmt)
            self.execute("DELETE FROM schema_migrations")
            self.execute(
                "INSERT INTO schema_migrations(version, migrated_at) VALUES (?, ?)",
                (len(self.SCHEMA), time.time()),
            )

    @property
    def version(self):
        try:
            return self.query("SELECT version FROM schema_migrations")[0][0]
        except (IndexError, sqlite3.Error):
            return 0

    @property
    def _credentials_db_path(self):
        config_dir = os.environ.get(
            env.CONFIG_DIR, os.path.join(os.path.expanduser("~"), ".config", "wandb")
        )
        wandb.util.mkdir_exists_ok(config_dir)
        return os.path.join(config_dir, "credentials.db")

    def token(self, host, client_id):
        rows = self.query(
            "SELECT token FROM tokens WHERE host = ? AND client_id = ?",
            (host, client_id),
        )
        if len(rows) == 0:
            return None
        return json.loads(rows[0][0])

    @property
    def tokens(self):
        return self.query("SELECT host, token, expiration FROM tokens")

    def query(self, query, variables=None):
        return self.execute(query, variables, commit=False, fetch=True)

    def execute(self, stmt, variables=None, commit=True, fetch=False):
        with closing(sqlite3.connect(self._credentials_db_path)) as connection:
            with closing(connection.cursor()) as cursor:
                result = cursor.execute(stmt, variables or ())
                if commit:
                    connection.commit()
                if fetch:
                    return result.fetchall()

    def save(self, token, host, client_id):
        self.execute(
            """
            INSERT INTO tokens(host, client_id, token, expiration)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(host, client_id) DO UPDATE SET
                    token=excluded.token,
                    client_id=excluded.client_id,
                    expiration=excluded.expiration;
            """,
            (
                host,
                client_id,
                json.dumps(token),
                int(time.time()) + token.get("expires_in", 60 * 60),
            ),
        )
