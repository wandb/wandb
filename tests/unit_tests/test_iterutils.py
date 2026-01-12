from __future__ import annotations

from itertools import repeat, tee

from hypothesis import example, given
from hypothesis.strategies import integers, iterables, sampled_from
from pytest import raises
from wandb._iterutils import one


@given(iterable=iterables(integers(), min_size=1, max_size=1))
def test_one_on_single_item_iterable(iterable):
    """Check that `one()` returns the only item in a single-item iterable."""
    # Copy the iterator so we can get the expected result from the first copy,
    # while passing the second copy to the tested function.
    test_iterable, ref_iterable = tee(iterable)
    expected = next(ref_iterable)
    assert one(test_iterable) == expected


@given(iterable=sampled_from([tuple(), [], iter([]), range(0), set(), dict()]))
def test_one_on_empty_iterable(iterable):
    """Check that `one()` raises an error on an empty iterable."""
    with raises(ValueError):
        one(iterable)


@example(iterable=repeat(1))  # Test at least one infinite iterator
@given(iterable=iterables(integers(), min_size=2, max_size=5))
def test_one_on_multi_item_iterable(iterable):
    """Check that `one()` raises an error on a multi-item iterable."""
    with raises(ValueError):
        one(iterable)
