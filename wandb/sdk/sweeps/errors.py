"""Errors and error reporting shared by the schedulers that drive sweeps."""

import traceback


class SweepNotFoundError(Exception):
    """Raised when a sweep is not found, typically because it was deleted."""


def format_caught_error(headline: str) -> str:
    """Append the exception being handled and its traceback to a headline.

    Call from an `except` block, where the error is printed once and not
    re-raised.

    Args:
        headline: What failed, in a sentence.
    """
    return f"{headline}\n{traceback.format_exc().rstrip()}"
