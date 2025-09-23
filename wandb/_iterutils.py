from __future__ import annotations

from collections.abc import Hashable
from typing import TYPE_CHECKING, Any, Iterable, TypeVar, Union, overload

if TYPE_CHECKING:
    T = TypeVar("T")
    HashableT = TypeVar("HashableT", bound=Hashable)
    ClassInfo = Union[type[T], tuple[type[T], ...]]


@overload
def always_list(obj: Iterable[T], base_type: ClassInfo = ...) -> list[T]: ...
@overload
def always_list(obj: T, base_type: ClassInfo = ...) -> list[T]: ...
def always_list(obj: Any, base_type: Any = (str, bytes)) -> list[T]:
    """Return a guaranteed list of objects from a single instance OR iterable of such objects.

    By default, assume the returned list should have string-like elements (i.e. `str`/`bytes`).

    Adapted from `more_itertools.always_iterable`, but simplified for internal use.  See:
    https://more-itertools.readthedocs.io/en/stable/api.html#more_itertools.always_iterable
    """
    return [obj] if isinstance(obj, base_type) else list(obj)


def unique_list(iterable: Iterable[HashableT]) -> list[HashableT]:
    """Return a deduplicated list of items from the given iterable, preserving order."""
    # Trick for O(1) uniqueness check that maintains order
    return list(dict.fromkeys(iterable))


def one(
    iterable: Iterable[T],
    too_short: type[Exception] | Exception | None = None,
    too_long: type[Exception] | Exception | None = None,
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
    except StopIteration:
        raise (too_short or ValueError("Expected 1 item in iterable, got 0")) from None

    # ...the second item doesn't
    try:
        _ = next(it)
    except StopIteration:
        return obj
    raise (
        too_long or ValueError("Expected 1 item in iterable, got multiple")
    ) from None
