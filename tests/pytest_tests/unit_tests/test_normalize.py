import json

import pytest
import requests
from wandb.apis.normalize import normalize_exceptions
from wandb.errors import CommError, Error


def raise_exception():
    raise Exception("test")


def response_factory(status_code, json_data=None):
    response = requests.Response()
    if json_data is not None:
        response._content = json.dumps(json_data).encode()
    response.status_code = status_code
    return response


def raise_http_error(response):
    raise requests.HTTPError("HTTP error occurred", response=response)


def raise_wandb_error():
    raise Error("W&B error occurred")


@pytest.mark.parametrize(
    "func, args, error, message",
    [
        (raise_exception, (), CommError, "test"),
        (raise_http_error, (response_factory(404),), CommError, r"<Response \[404\]>"),
        (
            raise_http_error,
            (response_factory(404, {"errors": "not found"}),),
            CommError,
            r"<Response \[404\]>",
        ),
        (
            raise_http_error,
            (response_factory(404, {"errors": ["not found"]}),),
            CommError,
            "not found",
        ),
        (raise_wandb_error, (), Error, "W&B error occurred"),
    ],
)
def test_normalize_http_error(func, args, error, message):
    with pytest.raises(error, match=message):
        normalize_exceptions(func)(*args)
