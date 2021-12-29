import os
import configparser

from google.auth import _helpers
from google.auth import credentials
from google.auth import aws
from google.auth.transport.requests import Request


class WandbCredentials(credentials.Credentials):
    def __init__(self, url):
        super(WandbCredentials, self).__init__()
        # TODO: refactor or get from the server...
        federate = os.getenv("WANDB_FEDERATE")
        self.base_url = url.replace("/graphql", "")
        self.credentials = credentials.AnonymousCredentials()
        if federate != "":
            if federate == "aws":
                self._maybe_load_aws_env()
                self.credentials = aws.Credentials.from_info(
                    {
                        "audience": "https://api.wandb.ai/v1",
                        "subject_token_type": "urn:ietf:params:aws:token-type:aws4_request",
                        "token_url": f"{self.base_url}/oidc/federate",
                        "credential_source": {
                            "environment_id": "aws1",
                            "regional_cred_verification_url": "https://sts.{region}.amazonaws.com?Action=GetCallerIdentity&Version=2011-06-15",
                            # "region_url": "http://169.254.169.254/latest/meta-data/placement/availability-zone",
                            # "url": "http://169.254.169.254/latest/meta-data/iam/security-credentials",
                        },
                    }
                )

    def _maybe_load_aws_env(self):
        """For developer credentials, we load them into the environment if they
        aren't there."""
        profile = os.environ.get("AWS_PROFILE", "default")
        if os.getenv("AWS_ACCESS_KEY_ID") is None:
            cred_file = os.path.expanduser("~/.aws/credentials")
            if os.path.exists(cred_file):
                parser = configparser.ConfigParser()
                parser.add_section(profile)
                parser.read(cred_file)
                for k in parser[profile]:
                    if k.startswith("aws_"):
                        os.environ[k.upper()] = parser[profile][k]
        if os.getenv("AWS_REGION") is None:
            conf_file = os.path.expanduser("~/.aws/config")
            if os.path.exists(conf_file):
                parser = configparser.ConfigParser()
                parser.add_section(profile)
                parser.read(cred_file)
                os.environ["AWS_REGION"] = parser[profile].get("region", "us-east-1")

    # TODO: override token_url for the default authenticator, look into reauth
    @property
    def expired(self):
        return self.credentials.expired

    @property
    def valid(self):
        return self.credentials.valid

    def refresh(self, request=None):
        if request is None:
            request = Request()
        res = self.credentials.refresh(request)
        self.token = self.credentials.token
        return res

    def apply(self, headers, token=None):
        """Apply the token to the authentication header.
        Args:
            headers (Mapping): The HTTP request headers.
            token (Optional[str]): If specified, overrides the current access
                token.
        """
        headers["X-Wandb-ID-Token"] = "{}".format(
            _helpers.from_bytes(token or self.token)
        )
