from graphql.language.parser import parse
from graphql.language.printer import print_ast
from graphql.language.source import Source
import requests
import six
import wandb
from wandb.errors import GQLError


def gql(request_string):
    """Converts a request string into a graphql-core Source document

    Returns:
        data: the dictionary of data queried

    Raises:
        wandb.errors.GQLError if the source document is invalid
    """

    if isinstance(request_string, six.string_types):
        source = Source(request_string, "GraphQL request")
        return parse(source)
    else:
        raise GQLError('Received incompatible request "{}".'.format(request_string))


class GQLClient(object):
    def __init__(
        self, settings=None, headers=None, timeout=None, api_key=None, url=None
    ):
        if not settings:
            settings = wandb.setup().settings
        self._settings = settings
        self._session = requests.Session()
        self.url = url
        self.headers = headers
        self.auth = None
        if api_key is not None:
            self.auth = ("key", api_key)
        self.default_timeout = timeout

    @property
    def authenticated(self):
        return self.auth is not None

    @property
    def session(self):
        return self._session

    def reauth(self, key):
        self.auth = ("key", key)

    def execute(self, document, variable_values=None, timeout=None):
        """Executes a query against the graphql backend.

        Returns:
            data: the dictionary of data queried

        Raises:
            requests.RequestsException if the connection fails, the response isn't
                a 200, or the response doesn't contain valid JSON.
        """
        query_str = print_ast(document)
        payload = {"query": query_str, "variables": variable_values or {}}
        post_args = {
            "headers": self.headers,
            "auth": self.auth,
            "timeout": timeout or self.default_timeout,
            "json": payload,
        }
        response = self._session.post(self.url, **post_args)
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
        except ValueError:
            # Mark the request as 500 to retry cases where a misconfigured proxy returns
            # HTML with a 200 response code and display a better error message.
            response.status_code = 500
            result = {
                "errors": [{"message": "{} did not return valid JSON".format(self.url)}]
            }
        # Display a nicer error message for known GQL errors
        if response.status_code >= 400 and len(result.get("errors", [])) > 0:
            if isinstance(result["errors"][0], dict):
                message = result["errors"][0].get("message", "GraphQL API Error")
            else:
                # TODO(cvp): I think this only happens in our test mocks, but just to
                # be safe we handle cases where a server returns {"errors": ["message"]}
                message = result["errors"][0]
            raise requests.HTTPError(message, response=response)
        # Generic error when the server doesn't return {"errors":...}
        response.raise_for_status()
        # NOTE: there could be a future scenario where we want access to errors on a 200
        # response.  Currently the API will always return a non-200 response when there
        # are errors so we just disregard that case for now.
        return result.get("data")
