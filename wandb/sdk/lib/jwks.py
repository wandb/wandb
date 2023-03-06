import hashlib
import json
import os
import time
from typing import Optional

from authlib.common import encoding
from authlib.jose import JsonWebKey, JsonWebToken, KeySet, OKPKey, RSAKey
from authlib.oauth2.rfc7523 import PrivateKeyJWT

from wandb import util

from . import filesystem


class JWKS:
    # TODO: support multiple hosts
    PATH = os.path.join(os.path.expanduser("~"), ".config", "wandb", "wandb-sdk.jwks")

    def __init__(self, token_endpoint: str, alg: str = "RSA"):
        self.token_endpoint = token_endpoint
        self.jwt = JsonWebToken(["EdDSA", "RS256"])
        filesystem.mkdir_exists_ok(
            os.path.join(os.path.expanduser("~"), ".config", "wandb")
        )
        # TODO: support multiple entities
        if alg == "RSA":
            self.alg = "RS256"
        else:
            self.alg = "EdDSA"
        if os.path.exists(self.PATH):
            self.jwks = JsonWebKey.import_key_set(open(self.PATH).read())
        else:
            # Google Cloud KMS supports the following key types:
            # JsonWebKey.generate_key("EC", "P-256", is_private=True)
            # JsonWebKey.generate_key("RSA", 3072, is_private=True)
            if alg == "RSA":
                key = JsonWebKey.generate_key(alg, 2048, is_private=True)
            else:
                key = JsonWebKey.generate_key(
                    alg,
                    "Ed25519",
                    options={"kid": util.generate_id(12)},
                    is_private=True,
                )
            self.jwks = KeySet(keys=[key])
            self.persist()
        self.key: RSAKey | OKPKey = self.jwks.keys[-1]

    @classmethod
    @property
    def configured(cls):
        return os.path.exists(cls.PATH)

    def persist(self):
        with open(self.PATH, "w") as f:
            f.write(self.jwks.as_json(is_private=True))
        os.chmod(self.PATH, 0o600)

    @property
    def client_id(self):
        return self.jwks.keys[0].kid

    def public_jwk(self, as_json: bool = True, pem: bool = False):
        if pem:
            return self.key.as_pem()
        else:
            key = self.key.as_dict()
            if as_json:
                return json.dumps(key)
            else:
                return key

    def fetch_token(
        self,
        subject: str,
        expires_in: Optional[int] = None,
        scope: Optional[str] = None,
    ) -> dict[str, str]:
        session = self.delegating_session()
        # TODO: wire up audience
        return session.fetch_token(
            grant_type="client_credentials",
            acts_as=subject,
            scope=scope or "runs.write",
            expires_in=expires_in,
        )

    def link(self, token: str):
        from wandb.apis.public import Api

        # TODO: add a flag to disable requiring api key
        api = Api(api_key="X" * 40)
        res = api.client.execute(
            Api.CREATE_CLIENT, {"jwk": self.public_jwk(), "token": token}
        )
        kid = res["createClient"]["clientId"]
        # This scopes by entity id
        # TODO: maybe make the token do this?
        self.jwks.keys[0]._dict_data["kid"] = kid
        self.persist()

    def delegating_session(
        self,
    ):
        from authlib.integrations.requests_client import OAuth2Session

        sess = OAuth2Session(
            client_id=self.client_id,
            client_secret=self.key,
            scope="runs.write",
            token_endpoint=self.token_endpoint,
            token_endpoint_auth_method="private_key_jwt",
        )
        sess.register_client_auth_method(
            PrivateKeyJWT(self.token_endpoint, alg=self.alg)
        )
        return sess

    # TODO: support other assertions
    def assertion(self, subject: str):
        # TODO: make iss hostname?
        return self.jwt.encode(
            {"alg": self.alg, "iat": int(time.time())},
            {"iss": "wandb", "sub": subject, "aud": "wandb-sdk"},
            self.key,
        ).decode("utf-8")


# TODO: likely get rid of this
class GCP:
    def __init__(self, token_endpoint: str, key_path: str):
        self.token_endpoint = token_endpoint
        self.key: Optional[RSAKey] = None
        self.jwt = JsonWebToken(["RS256", "RS512"])
        self._key_path = key_path
        parts = self._key_path.split("/")
        assert (
            len(parts) == 10 and parts[0] == "projects"
        ), "Invalid key path, expected: projects/W/locations/X/keyRings/Y/cryptoKeys/Z/cryptoKeyVersions/N"
        self.kid = hashlib.sha1(self._key_path.encode("utf8", "strict")).hexdigest()[
            :32
        ]
        self._kms = util.get_module(
            "google.cloud.kms",
            required="google cloud kms required: pip install google-cloud-kms",
        )
        self._auth = util.get_module("google.auth.exceptions")
        try:
            self._client = self._kms.KeyManagementServiceClient()
        except self._auth.DefaultCredentialsError:
            raise Exception(
                "Could not authenticate with google cloud. Please run `gcloud auth application-default login`"
            )
        res = self._client.get_crypto_key_version(request={"name": self._key_path})
        self._alg = res.algorithm
        # TODO: support other EC algs?
        assert self._alg in [
            "RSA_SIGN_PSS_2048_SHA256",
            "RSA_SIGN_PSS_3072_SHA256",
            "RSA_SIGN_PSS_4096_SHA256",
        ]

    def public_key(self, pem: bool = False):
        if self.key is None:
            # TODO: type
            public_key = self._client.get_public_key(request={"name": self._key_path})

            if not public_key.name == self._key_path:
                raise Exception(
                    "The request sent to the server was corrupted in-transit."
                )

            # TODO: decide if crc checks make sense
            # https://cloud.google.com/kms/docs/data-integrity-guidelines
            self.key = JsonWebKey.import_key(public_key.pem)
        if pem:
            return self.key.as_pem()
        else:
            return self.key.as_dict(kid=self.kid)

    def assertion(self, subject):
        # TODO: wire through alg
        header = {"alg": "RS256", "kid": self.kid}
        payload = {
            "iss": "wandb-gcp",
            "sub": subject,
            "aud": "wandb-cli",
            "iat": int(time.time()),
        }
        message = (
            encoding.json_b64encode(header) + b"." + encoding.json_b64encode(payload)
        )
        hash_ = hashlib.sha256(message).digest()

        sign_response = self._client.asymmetric_sign(
            request={"name": self._key_path, "digest": {"sha256": hash_}}
        )
        if not sign_response.name == self._key_path:
            raise Exception("The request sent to the server was corrupted in-transit.")
        sig = encoding.urlsafe_b64encode(sign_response.signature)

        return b".".join([message, sig]).decode("utf-8")
