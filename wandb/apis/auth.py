import os
from typing import Optional

import requests
from authlib.common.encoding import json_loads, urlsafe_b64decode
from authlib.integrations.requests_client import OAuth2Auth

import wandb
from wandb import env


class OIDCAuth(OAuth2Auth):
    def __init__(self, token_endpoint: str, access_token: Optional[str] = None):
        self._token_endpoint = token_endpoint
        self._access_token = access_token
        self._expires_at = None
        if access_token:
            claim_bytes = urlsafe_b64decode(access_token.split(".")[1].encode("utf-8"))
            claims = json_loads(claim_bytes.decode("utf-8"))
            self._expires_at = claims["exp"]
        elif os.getenv(env.OIDC_TOKEN_PATH):
            try:
                with open(os.environ[env.OIDC_TOKEN_PATH], "r") as f:
                    token = f.read()
                self.exchange_token(token)
            except Exception as e:
                wandb.termwarn("Failed to federate identity: %s" % e)
        # TODO: once we have more complex oauth we'll need to pass in a client
        self._client = None
        super(OIDCAuth, self).__init__(
            {"access_token": access_token, "expires_at": self._expires_at},
            client=self._client,
        )

    def exchange_token(self, token: str):
        res = requests.post(
            self._token_endpoint + "?client_id=wandb-sdk-federated",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            },
        )
        res.raise_for_status()
        tokens = res.json()
        self._expires_at = tokens["expires_at"]
        self._access_token = tokens["access_token"]
