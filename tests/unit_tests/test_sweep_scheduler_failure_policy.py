from __future__ import annotations

from http import HTTPStatus

import pytest
from wandb.errors import CommError
from wandb.proto.wandb_api_pb2 import ApiErrorResponse
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps import SweepNotFoundError
from wandb.sdk.sweeps.scheduler.failure_policy import Disposition, classify, http_status


def api_error(status: int | None = None, message: str = "boom") -> WandbApiFailedError:
    """A W&B API failure as wandb-core reports it.

    Args:
        status: The upstream HTTP status. None models a failure that never
            reached an HTTP response, which is how a transport error or a
            service process that isn't running arrives.
        message: The failure message.
    """
    if status is None:
        return WandbApiFailedError(message)
    return WandbApiFailedError(
        message,
        ApiErrorResponse(message=message, http_status=status),
    )


def wrapped(error: WandbApiFailedError) -> CommError:
    """`error` as `normalize_exceptions` re-raises it."""
    return CommError(error.args[0], error)


PERMANENT_STATUSES = [
    HTTPStatus.BAD_REQUEST,
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.CONFLICT,
    HTTPStatus.GONE,
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.NOT_IMPLEMENTED,
]

TRANSIENT_STATUSES = [
    HTTPStatus.REQUEST_TIMEOUT,
    HTTPStatus.INTERNAL_SERVER_ERROR,
    HTTPStatus.BAD_GATEWAY,
    HTTPStatus.SERVICE_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT,
]


@pytest.mark.parametrize("status", PERMANENT_STATUSES)
def test_permanent_statuses_are_fatal(status: int) -> None:
    assert classify(api_error(status)) is Disposition.FATAL
    assert classify(wrapped(api_error(status))) is Disposition.FATAL


@pytest.mark.parametrize("status", TRANSIENT_STATUSES)
def test_transient_statuses_keep_the_loop_polling(status: int) -> None:
    assert classify(api_error(status)) is Disposition.TRANSIENT
    assert classify(wrapped(api_error(status))) is Disposition.TRANSIENT


def test_not_found_is_reported_separately() -> None:
    assert classify(api_error(HTTPStatus.NOT_FOUND)) is Disposition.NOT_FOUND
    assert classify(wrapped(api_error(HTTPStatus.NOT_FOUND))) is Disposition.NOT_FOUND


def test_too_many_requests_is_rate_limited() -> None:
    error = api_error(HTTPStatus.TOO_MANY_REQUESTS)
    assert classify(error) is Disposition.RATE_LIMITED
    assert classify(wrapped(error)) is Disposition.RATE_LIMITED


def test_failure_without_an_http_response_is_transient() -> None:
    """A failure that never reached the server is a transport problem."""
    # wandb-core reports no status at all when the service process is gone.
    assert classify(api_error(None)) is Disposition.TRANSIENT
    assert classify(wrapped(api_error(None))) is Disposition.TRANSIENT
    # It reports 0 when the request itself had no HTTP response.
    assert classify(api_error(0)) is Disposition.TRANSIENT


def test_unrecognized_client_error_is_fatal() -> None:
    assert classify(api_error(HTTPStatus.EXPECTATION_FAILED)) is Disposition.FATAL


def test_non_api_error_is_fatal() -> None:
    """An error that isn't a W&B API failure would just fail again."""
    # A malformed run config reaches the scheduler as a bare CommError, because
    # normalize_exceptions wraps every exception, not just network ones.
    assert classify(CommError("Unable to convert 3 to a dict")) is Disposition.FATAL
    assert classify(TypeError("not a dict")) is Disposition.FATAL


def test_missing_sweep_is_not_found() -> None:
    """A deleted sweep answers 200 with a null sweep, so `Sweep.load` raises."""
    error = SweepNotFoundError("Could not find sweep <Sweep entity/project/sweep_id>")
    assert classify(error) is Disposition.NOT_FOUND


def test_unrelated_value_error_is_fatal() -> None:
    assert classify(ValueError("Run r is already in flight")) is Disposition.FATAL


def test_http_status_reads_requests_style_errors() -> None:
    """Paths that talk HTTP directly still expose a status."""

    class Response:
        status_code = int(HTTPStatus.SERVICE_UNAVAILABLE)

    class HttpError(Exception):
        response = Response()

    assert http_status(HttpError()) == HTTPStatus.SERVICE_UNAVAILABLE
    assert classify(HttpError()) is Disposition.TRANSIENT


def test_http_status_is_none_without_a_status() -> None:
    assert http_status(api_error(None)) is None
    assert http_status(api_error(0)) is None
    assert http_status(CommError("no status here")) is None
