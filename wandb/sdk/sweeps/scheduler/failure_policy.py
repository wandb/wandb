from __future__ import annotations

from enum import Enum
from http import HTTPStatus

from wandb.errors import CommError
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps.errors import SweepNotFoundError

__all__ = ["Disposition", "classify", "http_status"]


class Disposition(Enum):
    """What the scheduler loop should do about a failed API call."""

    FATAL = "fatal"
    """The call will never succeed; end the loop."""

    NOT_FOUND = "not_found"
    """The sweep or run is gone; end the loop."""

    TRANSIENT = "transient"
    """May clear up on its own; keep polling, but less often."""

    RATE_LIMITED = "rate_limited"
    """The server is asking us to slow down; poll less often."""


# A malformed query (400, 422), bad credentials (401, 403), a resource gone
# or conflicted (409, 410), an oversized payload (413), or an unimplemented
# operation (501). wandb-core retries none of these.
_FATAL_STATUSES = frozenset(
    {
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.CONFLICT,
        HTTPStatus.GONE,
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        HTTPStatus.NOT_IMPLEMENTED,
    }
)


def _api_failure(exc: BaseException) -> WandbApiFailedError | None:
    """Return the W&B API failure behind `exc`, if there is one.

    `normalize_exceptions` wraps it in a `CommError`, except under
    `WANDB_DEBUG`, which re-raises it untouched -- so both forms turn up.
    """
    if isinstance(exc, WandbApiFailedError):
        return exc
    if isinstance(exc, CommError) and isinstance(exc.exc, WandbApiFailedError):
        return exc.exc
    return None


def http_status(exc: BaseException) -> int | None:
    """The upstream HTTP status behind `exc`, or None if it carries none.

    None means either that the failure never reached an HTTP response, or that
    `exc` is not a W&B API failure at all; `classify` tells those apart.

    Args:
        exc: The exception to read a status off of.
    """
    if (api_failure := _api_failure(exc)) is not None:
        if api_failure.response is None:
            return None
        # http_status is 0 when the failure had no HTTP response at all.
        return api_failure.response.http_status or None

    # Paths that talk HTTP directly raise `requests.HTTPError` instead. None
    # of the scheduler's calls do today, but reading it keeps a future one from
    # being misclassified silently.
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) and status else None


def classify(exc: BaseException) -> Disposition:
    """Decide what the scheduler loop should do about `exc`.

    Args:
        exc: The exception raised by a W&B API call.
    """
    # A deleted sweep answers 200 with a null sweep rather than 404, so this
    # is the signal that it is gone.
    if isinstance(exc, SweepNotFoundError):
        return Disposition.NOT_FOUND

    status = http_status(exc)
    if status is None:
        # No status on an API failure means a transport problem. Anything else
        # never made a request -- a bug or a data error -- and the next poll
        # would hit it again just as surely.
        return Disposition.TRANSIENT if _api_failure(exc) else Disposition.FATAL

    if status == HTTPStatus.NOT_FOUND:
        return Disposition.NOT_FOUND
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return Disposition.RATE_LIMITED
    if status in _FATAL_STATUSES:
        return Disposition.FATAL
    # 501 is fatal and already returned above.
    if status == HTTPStatus.REQUEST_TIMEOUT or status >= 500:
        return Disposition.TRANSIENT
    # An unrecognized 4xx: assume our request is at fault and would fail again.
    return Disposition.FATAL
