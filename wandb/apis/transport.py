"""This was mostly copied from:

https://github.com/graphql-python/gql/blob/v2.x/gql/transport/requests.py

It was modified to always bubble up any HTTP status errors ahead of checking
for errors in the response body.  Look for comments that start with # CVP.
"""
from __future__ import absolute_import

from typing import Any, Dict, Union

from gql.transport import Transport
try:
    from graphql.execution import ExecutionResult
    from graphql.language.printer import print_ast
except ImportError:
    # gql 3.x exposes these at the top level
    from graphql import print_ast, ExecutionResult
import requests
from requests.adapters import HTTPAdapter, Retry
from requests.auth import AuthBase
from requests.cookies import RequestsCookieJar


class RequestsHTTPTransport(Transport):
    """Transport to execute GraphQL queries on remote servers.
    The transport uses the requests library to send HTTP POST requests.
    """

    def __init__(
        self,  # type: RequestsHTTPTransport
        url,  # type: str
        headers=None,  # type: Dict[str, Any]
        cookies=None,  # type: Union[Dict[str, Any], RequestsCookieJar]
        auth=None,  # type: AuthBase
        use_json=True,  # type: bool
        timeout=None,  # type: int
        verify=True,  # type: bool
        retries=0,  # type: int
        method="POST",  # type: str
        **kwargs  # type: Any
    ):
        """Initialize the transport with the given request parameters.
        :param url: The GraphQL server URL.
        :param headers: Dictionary of HTTP Headers to send with the :class:`Request` (Default: None).
        :param cookies: Dict or CookieJar object to send with the :class:`Request` (Default: None).
        :param auth: Auth tuple or callable to enable Basic/Digest/Custom HTTP Auth (Default: None).
        :param use_json: Send request body as JSON instead of form-urlencoded (Default: False).
        :param timeout: Specifies a default timeout for requests (Default: None).
        :param verify: Either a boolean, in which case it controls whether we verify
            the server's TLS certificate, or a string, in which case it must be a path
            to a CA bundle to use. (Default: True).
        :param retries: Pre-setup of the requests' Session for performing retries
        :param method: HTTP method used for requests. (Default: POST).
        :param kwargs: Optional arguments that ``request`` takes. These can be seen at the :requests_: source code
            or the official :docs_:
        .. _requests: https://github.com/psf/requests/blob/master/requests/api.py
        .. _docs: https://requests.readthedocs.io/en/master/
        """
        self.url = url
        self.headers = headers
        self.cookies = cookies
        self.auth = auth
        self.use_json = use_json
        self.default_timeout = timeout
        self.verify = verify
        self.method = method
        self.kwargs = kwargs

        # Creating a session that can later be re-use to configure custom mechanisms
        self.session = requests.Session()

        # If we specified some retries, we provide a predefined retry-logic
        if retries > 0:
            adapter = HTTPAdapter(
                max_retries=Retry(
                    total=retries,
                    backoff_factor=0.1,
                    status_forcelist=[500, 502, 503, 504],
                )
            )
            for prefix in "http://", "https://":
                self.session.mount(prefix, adapter)

    def execute(
        self, document, variable_values=None, operation_name=None, timeout=None
    ):
        # type: (Document, Dict, str, int) -> ExecutionResult
        """Execute the provided document AST against the configured remote server.
        This uses the requests library to perform a HTTP POST request to the remote server.
        :param document: GraphQL query as AST Node object.
        :param variable_values: Dictionary of input parameters (Default: None).
        :param operation_name: Name of the operation that shall be executed.
            Only required in multi-operation documents (Default: None).
        :param timeout: Specifies a default timeout for requests (Default: None).
        :return: The result of execution. `data` is the result of executing the query,
            `errors` is null if no errors occurred, and is a non-empty array if an error occurred.
        """
        query_str = print_ast(document)
        # CVP: added variables to every request
        payload = {"query": query_str, "variables": {}}  # type: Dict
        if variable_values:
            payload["variables"] = variable_values
        if operation_name:
            payload["operationName"] = operation_name

        data_key = "json" if self.use_json else "data"
        post_args = {
            "headers": self.headers,
            "auth": self.auth,
            "cookies": self.cookies,
            "timeout": timeout or self.default_timeout,
            "verify": self.verify,
            data_key: payload,
        }

        # Pass kwargs to requests post method
        post_args.update(self.kwargs)

        # Using the created session to perform requests
        response = self.session.request(self.method, self.url, **post_args)  # type: ignore
        # CVP: always raise for HTTP status
        response.raise_for_status()
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
        except ValueError:
            result = {}

        if "errors" not in result and "data" not in result:
            # CVP: no need to raise here
            # response.raise_for_status()
            raise requests.HTTPError(
                "Server did not return a GraphQL result", response=response
            )
        return ExecutionResult(errors=result.get("errors"), data=result.get("data"))

    def close(self):
        """Closing the transport by closing the inner session"""
        self.session.close()
