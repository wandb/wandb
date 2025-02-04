from __future__ import annotations

from typing import Iterable, TypeVar

T = TypeVar("T")


def one(
    iterable: Iterable[T],
    too_short: Exception | None = None,
    too_long: Exception | None = None,
) -> T:
    """Return the only item in the iterable.

    Note:
        This is intended **only** as an internal helper/convenience function,
        and its implementation is directly adapted from `more_itertools.one`.
        Users needing similar functionality are strongly encouraged to use
        that library instead:
        https://more-itertools.readthedocs.io/en/stable/api.html#more_itertools.one

    Args:
        iterable: The iterable to get the only item from.
        too_short: Custom exception to raise if the iterable has no items.
        too_long: Custom exception to raise if the iterable has multiple items.

    Raises:
        ValueError or `too_short`: If the iterable has no items.
        ValueError or `too_long`: If the iterable has multiple items.
    """
    # For a general iterable, avoid inadvertently iterating through all values,
    # which may be costly or impossible (e.g. if infinite).  Only check that:

    # ... the first item exists
    it = iter(iterable)
    try:
        obj = next(it)
    except StopIteration as e:
        raise too_short or ValueError("Expected 1 item in iterable, got 0") from e

    # ...the second item doesn't
    try:
        _ = next(it)
    except StopIteration:
        return obj
    raise too_long or ValueError("Expected 1 item in iterable, got multiple")
