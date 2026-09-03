from collections.abc import Hashable, Iterable
from itertools import repeat, tee

from hypothesis import example, given
from hypothesis.strategies import (
    binary,
    booleans,
    dictionaries,
    floats,
    integers,
    iterables,
    lists,
    none,
    recursive,
    sampled_from,
    text,
)
from pytest import raises
from wandb._iterutils import merge_dicts, one

hashables = (
    none() | booleans() | integers() | floats(allow_nan=False) | text() | binary()
)
values = recursive(
    hashables,
    lambda children: (
        lists(children, max_size=5) | dictionaries(hashables, children, max_size=5)
    ),
    max_leaves=10,
)


@example(dicts=[])
@given(dicts=iterables(dictionaries(hashables, values), max_size=10))
def test_merge_dicts(dicts: Iterable[dict[Hashable, object]]):
    test_dicts, ref_dicts = tee(dicts)
    expected: dict[Hashable, object] = {}
    for d in ref_dicts:
        expected.update(d)

    assert merge_dicts(test_dicts) == expected


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
