"""A simple GraphQL client for sending queries and mutations.

Note: This was originally wandb/vendor/gql-0.2.0/wandb_gql/transport/requests.py
The only substantial change is to reuse a requests.Session object.
"""

from __future__ import annotations

from typing import Any, Callable

import requests
from wandb_gql.transport.http import HTTPTransport
from wandb_graphql.execution import ExecutionResult
from wandb_graphql.language import ast
from wandb_graphql.language.printer import print_ast

from wandb._analytics import tracked_func


class GraphQLSession(HTTPTransport):
    def __init__(
        self,
        url: str,
        auth: tuple[str, str] | Callable | None = None,
        use_json: bool = False,
        timeout: int | float | None = None,
        proxies: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Setup a session for sending GraphQL queries and mutations.

        Args:
            url (str): The GraphQL URL
            auth (tuple or callable): Auth tuple or callable for Basic/Digest/Custom HTTP Auth
            use_json (bool): Send request body as JSON instead of form-urlencoded
            timeout (int, float): Specifies a default timeout for requests (Default: None)
        """
        super().__init__(url, **kwargs)
        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        self.session.auth = auth
        self.default_timeout = timeout
        self.use_json = use_json

    def execute(
        self,
        document: ast.Node,
        variable_values: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> ExecutionResult:
        query_str = print_ast(document)
        payload = {"query": query_str, "variables": variable_values or {}}

        data_key = "json" if self.use_json else "data"

        headers = self.headers.copy() if self.headers else {}

        # If we're tracking a calling python function, include it in the headers
        if func_info := tracked_func():
            headers.update(func_info.to_headers())

        post_args = {
            "headers": headers or None,
            "cookies": self.cookies,
            "timeout": timeout or self.default_timeout,
            data_key: payload,
        }
        request = self.session.post(self.url, **post_args)
        request.raise_for_status()

        result = request.json()
        data, errors = result.get("data"), result.get("errors")
        if data is None and errors is None:
            raise RuntimeError(f"Received non-compatible response: {result}")
        return ExecutionResult(data=data, errors=errors)
