from __future__ import annotations

import re
from typing import NoReturn

import pytest
import requests
from wandb.apis.normalize import normalize_exceptions
from wandb.errors import CommError


def raise_exception(msg: str):
    raise Exception(msg)


def http_response(
    status_code: int,
    body: bytes | None = None,
    reason: str | None = None,
):
    response = requests.Response()
    if body is not None:
        response._content = body
    if reason is not None:
        response.reason = reason
    response.status_code = status_code
    return response


def test_exception():
    @normalize_exceptions
    def fn():
        raise Exception("test")

    with pytest.raises(CommError, match="test"):
        fn()


@normalize_exceptions
def raise_http_error(response: requests.Response) -> NoReturn:
    raise requests.HTTPError(response=response)


def test_empty_http_error():
    resp = http_response(404)

    with pytest.raises(CommError, match="HTTP 404"):
        raise_http_error(resp)


def test_http_error_with_reason():
    resp = http_response(404, reason="Not Found")

    with pytest.raises(CommError, match=re.escape("HTTP 404 (Not Found)")):
        raise_http_error(resp)


@pytest.mark.parametrize(
    "body, message",
    [
        (b"not JSON", "HTTP 500: not JSON"),
        (b'"JSON string"', 'HTTP 500: "JSON string"'),
        (b'{"bad field": 123}', 'HTTP 500: {"bad field": 123}'),
        (b'{"error": 123}', 'HTTP 500: {"error": 123}'),
        (b'{"errors": 123}', 'HTTP 500: {"errors": 123}'),
        (b'{"errors": "string"}', 'HTTP 500: {"errors": "string"}'),
    ],
)
def test_http_error_invalid_body(body, message):
    resp = http_response(500, body=body)

    with pytest.raises(CommError, match=re.escape(message)):
        raise_http_error(resp)


@pytest.mark.parametrize(
    "body, message",
    [
        (b'{"error": "string"}', "HTTP 500: string"),
        (b'{"error": {"message": "message"}}', "HTTP 500: message"),
        (
            b'{"errors": ["string", {"message": "nested message"}]}',
            "HTTP 500: string; nested message",
        ),
    ],
)
def test_http_error_valid_body(body, message):
    resp = http_response(500, body=body)

    with pytest.raises(CommError, match=re.escape(message)):
        raise_http_error(resp)
