from contextlib import closing
import json
import logging
import os
import sqlite3
import time
import webbrowser

from oauthlib.oauth2 import BackendApplicationClient  # type: ignore
import requests
from requests_oauthlib import OAuth2Session  # type: ignore
import wandb
from wandb import env

logger = logging.getLogger(__name__)
logging.getLogger("oauth2_session.py").setLevel(logging.INFO)


# TODO: we may want to override this when offloading auth...
def _add_bearer_token(
    self, uri, http_method="GET", body=None, headers=None, token_placement=None
):
    """Custom addition of our id_token to the authorization header.

    The default implementation adds the access_token to all requests.  The
    original implementation is here:
    https://github.com/oauthlib/oauthlib/blob/master/oauthlib/oauth2/rfc6749/clients/base.py#L149
    """
    if headers is None:
        headers = {}
    headers["Authorization"] = "Bearer {}".format(self.token.get("id_token"))
    return uri, headers, body


BackendApplicationClient._add_bearer_token = _add_bearer_token


class SessionManager(object):
    """
    A Session Manager provides an OAuth2Session that automatically rotates tokens
    """

    DEFAULT_DEVICE_URL = "https://wandb.auth0.com/oauth/device/code"
    DEFAULT_REFRESH_URL = "https://wandb.auth0.com/oauth/token"
    DEFAULT_CLIENT_ID = "0eVXWcQfxyjVvAYTVP0XtMzcAcB9DJue"
    DEFAULT_SCOPE = ["openid", "offline_access"]
    GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

    def __init__(self, settings=None, scopes=None):
        if not settings:
            settings = wandb.setup().settings
        self._settings = settings
        self._token_store = TokenStore(self._settings.base_url)
        self._discovery = None
        self._session = None
        discovery_url = os.getenv(env.DISCOVERY_URL)
        if discovery_url is not None:
            self._load_oidc(discovery_url)
        self._client_id = os.getenv(env.CLIENT_ID, self.DEFAULT_CLIENT_ID)
        self._client_secret = os.getenv(env.CLIENT_SECRET)
        self.scopes = scopes or self.DEFAULT_SCOPE
        if self._settings.auth_mode == "google":
            self._setup_google()

    @property
    def token(self):
        return self._token_store.token

    @property
    def client_id(self):
        return self._client_id

    @client_id.setter
    def client_id(self, client_id):
        self._client_id = client_id
        self._token_store.client_id = client_id

    @property
    def authorized(self):
        token = self.token or {}
        return token.get("id_token") is not None

    @property
    def refresh_url(self):
        if self._discovery is not None:
            return self._discovery["token_endpoint"]
        # TODO: actually handle local installations...
        if False and self._settings.base_url != "https://api.wandb.ai":
            return self._settings.base_url + "/oidc/token"
        return self.DEFAULT_REFRESH_URL

    @property
    def device_url(self):
        if self._discovery is not None:
            return self._discovery["device_authorization_endpoint"]
        # TODO: actually handle local installations...
        if False and self._settings.base_url != "https://api.wandb.ai":
            return self._settings.base_url + "/oidc/device_code"
        return self.DEFAULT_DEVICE_URL

    def session(self, force=False):
        # For an initial device code flow if we have no token
        if self.token is None:
            self.prompt_login()
        if self._session is None or force:
            # This session will automatically refresh the id_token
            refresh_args = {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
            client = BackendApplicationClient(client_id=self._client_id)
            # TODO: Handle InvalidGrantError...
            self._session = OAuth2Session(
                client=client,
                token=self.token,
                auto_refresh_url=self.refresh_url,
                auto_refresh_kwargs=refresh_args,
                token_updater=self.token_saver,
                scope=self.scopes,
            )
        return self._session

    def refresh(self):
        self._session.refresh_token(
            self.refresh_url,
            **{"client_id": self._client_id, "client_secret": self._client_secret}
        )

    def prompt_login(self, attempt_launch_browser=True):
        """This takes the user through the device code flow: https://tools.ietf.org/html/rfc8628

        We attempt to open the browser and present the user with a code.
        """

        try:
            res = requests.post(
                self.device_url,
                data={"client_id": self._client_id, "scope": " ".join(self.scopes)},
            )
            res.raise_for_status()
            device_flow = res.json()
            url = device_flow.get(
                "verification_uri_complete",
                device_flow.get(
                    "verification_uri", device_flow.get("verification_url")
                ),
            )
            if url is None:
                raise ValueError(
                    "Couldn't find url in device response: {}".format(device_flow)
                )
            expires_at = time.time() + device_flow["expires_in"]

            if wandb.util.launch_browser(attempt_launch_browser):
                webbrowser.open(url, new=1, autoraise=True)
                wandb.termlog("Browser opened, grant access with the following code:")
            else:
                wandb.termlog(
                    "Go to this url and enter the following code: {}".format(url)
                )
            wandb.termlog("  " + device_flow["user_code"])

            while True:
                body = {
                    "client_id": self._client_id,
                    "device_code": device_flow["device_code"],
                    "grant_type": self.GRANT_TYPE,
                }
                # Google requires a client secret
                if self._client_secret:
                    body["client_secret"] = self._client_secret
                res = requests.post(self.refresh_url, data=body)
                # TODO: handle cancelation
                logger.info("OIDC device polling status: {}".format(res.json()))
                if res.status_code != 200:
                    if time.time() > expires_at:
                        wandb.termwarn("Authentication timed out, please try again.")
                        break
                else:
                    payload = res.json()
                    if payload.get("refresh_token") is not None:
                        self.token_saver(payload)
                        wandb.termlog("Authentication successful!")
                        break
                time.sleep(device_flow.get("interval", 5))
            return self.token is not None
        except Exception as e:
            logger.exception(e)
            wandb.termerror("Failed to authenticate device")
            return False

    def _setup_google(self):
        auth = wandb.util.get_module(
            "google.auth",
            required="Run pip install google-auth to use auth_mode=google",
        )
        credentials, _ = auth.default()
        self._discovery = {
            "token_endpoint": credentials.token_uri,
            "device_authorization_endpoint": credentials.token_uri.replace(
                "/token", "/device/code"
            ),
        }
        self.client_id = credentials.client_id
        self._client_secret = credentials.client_secret
        self.scopes = credentials.scopes
        self.token_saver(
            {
                "access_token": "XXXX",
                "id_token": "XXXX",
                "refresh_token": credentials.refresh_token,
                "scope": self.scopes,
                "expires_at": time.time() - 10,
            }
        )
        self._session = None

    def _load_oidc(self, discovery_url):
        """
        Loads an OIDC discovery url and gets the token_endpoint and device_authorization_endpoint keys

        Raises:
            ValueError - if the OIDC server doesn't support device authorization
        """
        try:
            res = requests.get(discovery_url)
            res.raise_for_status()
            self._discovery = res.json()
            if self._discovery.get("token_endpoint") is None:
                raise ValueError(
                    "OIDC discovery url does not look valid, couldn't find token_endpoint"
                )
            if self._discovery.get("device_authorization_endpoint") is None:
                raise ValueError(
                    "OIDC server does not support RFC 8628 Device Authorization Grant"
                )
        except (requests.RequestException, ValueError) as e:
            wandb.termwarn("Unable to load OIDC discovery url: {}".format(e))

    def token_saver(self, token):
        return self._token_store.save(token)


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

    def __init__(self, host, client_id=None):
        self.host = host
        self.client_id = client_id
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
        return os.path.join(wandb.util.ensure_config_dir(), "credentials.db")

    @property
    def token(self):
        rows = self.query("SELECT token FROM tokens WHERE host = ?", (self.host,))
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

    def save(self, token, client_id=None):
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
                self.host,
                client_id or self.client_id,
                json.dumps(token),
                int(time.time()) + token.get("expires_in", 60 * 60),
            ),
        )
