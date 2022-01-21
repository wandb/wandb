import sys

from graphql.language.parser import parse
from graphql.language.printer import print_ast
from graphql.language.source import Source
import requests
import six
import wandb

# TODO: consolidate dynamic imports
PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.lib import oidc
else:
    from wandb.sdk_py27.lib import oidc


def gql(request_string):
    if isinstance(request_string, six.string_types):
        source = Source(request_string, "GraphQL request")
        return parse(source)
    else:
        raise Exception('Received incompatible request "{}".'.format(request_string))


class GQLClient(object):
    def __init__(
        self, settings=None, headers=None, timeout=None, api_key=None, url=None
    ):
        if not settings:
            settings = wandb.setup().settings
        self._settings = settings
        if settings.auth_mode in ["oidc", "google"]:
            self._session = oidc.SessionManager(self._settings).session()
        else:
            self._session = requests.Session()
        self.url = url
        self.headers = headers
        self.auth = None
        if api_key is not None:
            self.auth = ("key", api_key)
        self.default_timeout = timeout

    @property
    def authenticated(self):
        if self._settings.auth_mode in ["oidc", "google"]:
            return self._session.authorized
        else:
            return self.auth is not None

    @property
    def session(self):
        return self._session

    def reauth(self, key):
        self.auth = ("key", key)

    def execute(self, document, variable_values=None, timeout=None):
        query_str = print_ast(document)
        payload = {"query": query_str, "variables": variable_values or {}}
        post_args = {
            "headers": self.headers,
            "auth": self.auth,
            "timeout": timeout or self.default_timeout,
            "json": payload,
        }
        request = self._session.post(self.url, **post_args)
        request.raise_for_status()
        result = request.json()
        assert (
            "errors" in result or "data" in result
        ), 'Received non-compatible response "{}"'.format(result)
        if result.get("errors"):
            raise Exception(str(result.errors[0]))
        return result.get("data")
