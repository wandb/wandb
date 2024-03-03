import hashlib
import os
from typing import Optional

from authlib.integrations.requests_client import OAuth2Auth, OAuth2Session
from authlib.jose.util import extract_header
from authlib.oauth2.rfc7523 import JWTBearerGrant

import wandb
from wandb import env


class OIDCAuth(OAuth2Auth):
    def __init__(self, token_endpoint: str, access_token: Optional[str] = None):
        self._token_endpoint = token_endpoint
        self._introspect_endpoint = token_endpoint.replace("token", "introspect")
        self._access_token = access_token
        self._expires_at = 0
        if access_token:
            # TODO: this currently doesn't work
            res = self.introspect_token(access_token)
            if res.get("expires_at"):
                self._expires_at = res["expires_at"]
        self._client = OAuth2Session(
            client_id="wandb-federated",
            token_endpoint=self._token_endpoint,
        )
        super().__init__(
            {"access_token": access_token, "expires_at": self._expires_at},
            client=self._client,
        )

    def load_federation_token(self) -> Optional[str]:
        if os.getenv(env.OIDC_TOKEN_PATH):
            try:
                with open(os.environ[env.OIDC_TOKEN_PATH]) as f:
                    token = f.read()
                self.exchange_token(token)
                return token
            except Exception as e:
                wandb.termwarn("Failed to federate identity: %s" % e)
        return None

    def id_from_jwt(self, token: str) -> str:
        parts = token.encode("utf-8").split(b".")
        payload = extract_header(parts[1], ValueError)
        iss = payload.get("iss")
        sub = payload.get("sub")
        if iss is None or sub is None:
            raise ValueError("Invalid token")
        return "ft." + hashlib.md5(f"{iss}|{sub}".encode()).hexdigest()

    def introspect_token(self, token: str) -> dict:
        return self._client.introspect_token(self._introspect_endpoint, token=token)

    # We can likely override this for jwt_bearer
    def ensure_active_token(self, token) -> bool:
        refreshed = self._client.ensure_active_token(token) is True
        if not refreshed:
            refreshed = self.load_federation_token() is not None
        return refreshed

    # We may want to support this for AWS or SAML tokens
    def exchange_token(self, token: str) -> bool:
        id = self.id_from_jwt(token)
        self._client.client_id = id
        new_token = self._client.fetch_token(
            self._token_endpoint,
            assertion=token,
            grant_type=JWTBearerGrant.GRANT_TYPE,
        )
        print(new_token)
        if new_token.get("access_token"):
            if self._client.update_token:
                self._client.update_token(new_token, access_token=token)
            self._expires_at = new_token["expires_at"]
            self._access_token = new_token["access_token"]
            return True
        return False
