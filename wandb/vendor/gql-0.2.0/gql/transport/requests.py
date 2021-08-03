from __future__ import absolute_import

import requests
from graphql.execution import ExecutionResult
from graphql.language.printer import print_ast

from .http import HTTPTransport


class RequestsHTTPTransport(HTTPTransport):
    def __init__(self, url, auth=None, use_json=False, timeout=None, **kwargs):
        """
        :param url: The GraphQL URL
        :param auth: Auth tuple or callable to enable Basic/Digest/Custom HTTP Auth
        :param use_json: Send request body as JSON instead of form-urlencoded
        :param timeout: Specifies a default timeout for requests (Default: None)
        """
        super(RequestsHTTPTransport, self).__init__(url, **kwargs)
        self.auth = auth
        self.default_timeout = timeout
        self.use_json = use_json

    def execute(self, document, variable_values=None, timeout=None):
        query_str = print_ast(document)
        payload = {
            'query': query_str,
            'variables': variable_values or {}
        }

        data_key = 'json' if self.use_json else 'data'
        post_args = {
            'headers': self.headers,
            'auth': self.auth,
            'cookies': self.cookies,
            'timeout': timeout or self.default_timeout,
            data_key: payload
        }
        request = requests.post(self.url, **post_args)
        request.raise_for_status()

        result = request.json()
        assert 'errors' in result or 'data' in result, 'Received non-compatible response "{}"'.format(result)
        return ExecutionResult(
            errors=result.get('errors'),
            data=result.get('data')
        )
