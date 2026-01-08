from __future__ import annotations

from collections import deque
from itertools import tee, zip_longest
from typing import Iterable, TypeVar

from hypothesis import given
from hypothesis.strategies import (
    SearchStrategy,
    integers,
    iterables,
    lists,
    slices,
    text,
)
from pytest import raises
from wandb.registries._freezable_list import FreezableList

T = TypeVar("T")

#: Max length of lists generated for testing.
MAX_SIZE: int = 10

#: Arbitrary key, used to share generated item(s) in a test.
SHARED_KEY: str = "SHARED"

# strategies to generate test objects
strings: SearchStrategy[str] = text(max_size=MAX_SIZE)
string_iterables: SearchStrategy[Iterable[str]] = iterables(strings, max_size=MAX_SIZE)
string_lists: SearchStrategy[list[str]] = lists(strings, max_size=MAX_SIZE)
indices: SearchStrategy[int] = integers(min_value=-MAX_SIZE * 2, max_value=MAX_SIZE * 2)


def test_init_without_args() -> None:
    """Check that instantiation with no arguments works like it does for builtin lists."""
    normal_list = list()
    addonly_list = FreezableList()

    assert addonly_list == normal_list == []


@given(
    # Valid iterables will have a finite (but not necessarily known) size
    init_items=string_iterables,
)
def test_init_with_iterable(init_items: Iterable[str]) -> None:
    """Check that instantiation from iterables works like it does for builtin lists."""
    # In case this is a consumable iterable, make a copy
    items_a, items_b = tee(init_items)

    normal_list = list(items_a)
    addonly_list = FreezableList(items_b)

    assert addonly_list == normal_list
    assert len(addonly_list) == len(normal_list)

    # For clarity, also directly check per-item order and equality
    for a, b in zip(addonly_list, normal_list):
        assert a == b

    # Check the frozen and draft items under the hood, even though they're not publicly exposed
    assert tuple(addonly_list._saved) == tuple(normal_list)
    assert tuple(addonly_list._draft) == ()


@given(
    init_items=string_lists,
    obj_to_append=strings,
)
def test_append(init_items: list[str], obj_to_append: str) -> None:
    """Test that append works correctly and handles duplicates as expected."""
    addonly_list = FreezableList(init_items)

    addonly_list.append(obj_to_append)

    if obj_to_append in init_items:
        # Should not add duplicate
        assert addonly_list == init_items
        assert tuple(addonly_list._draft) == ()
    else:
        # Should add new item
        assert addonly_list == [*init_items, obj_to_append]
        assert tuple(addonly_list._draft) == (obj_to_append,)


@given(
    init_items=string_lists,
    obj_to_remove=strings,
)
def test_remove(init_items: list[str], obj_to_remove: str) -> None:
    """Test that remove works correctly and handles errors as expected."""
    addonly_list = FreezableList(init_items)

    if obj_to_remove in init_items:
        # Should raise error when trying to remove frozen item
        with raises(ValueError, match=rf"(?i)cannot remove.*{obj_to_remove!r}"):
            addonly_list.remove(obj_to_remove)
    else:
        # Should raise error when item not in list
        with raises(ValueError):
            addonly_list.remove(obj_to_remove)


@given(
    init_items=string_lists,
    draft_objs=string_lists,
)
def test_freeze(init_items: list[str], draft_objs: list[str]) -> None:
    """Test that freeze correctly moves items from draft to frozen."""
    addonly_list = FreezableList(init_items)

    # Add draft items
    addonly_list += draft_objs

    addonly_list.freeze()

    # Check that all non-duplicate items are now frozen
    expected_frozen_seq = deque(init_items)
    for obj in draft_objs:
        if obj not in expected_frozen_seq:
            expected_frozen_seq.append(obj)

    assert tuple(addonly_list._saved) == tuple(expected_frozen_seq)
    assert tuple(addonly_list._draft) == ()


@given(
    items=string_lists,
    idx=indices,
)
def test_getitem(items: list[str], idx: int) -> None:
    """Test that getitem works correctly with both positive and negative indices."""
    addonly_list = FreezableList(items)

    size = len(items)

    if -size <= idx < size:  # In bounds
        assert addonly_list[idx] == items[idx]
    else:  # Out of bounds
        with raises(IndexError):
            addonly_list[idx]


@given(
    items=string_lists,
    idx=indices,
    value=strings,
)
def test_setitem(items: list[str], idx: int, value: str) -> None:
    """Test that setitem works correctly and handles errors."""
    addonly_list = FreezableList(items)

    frozen_size = len(items)

    if value in items:
        # Duplicate, no error but nothing should change
        addonly_list[idx] = value
        assert addonly_list == items
        assert len(addonly_list) == frozen_size

    # elif not items:
    #     # No frozen items, should just add to draft
    #     addonly_list[idx] = value
    #     assert addonly_list == [value]
    #     assert len(addonly_list) == 1

    elif -frozen_size <= idx < frozen_size:  # In bounds
        # Should raise error when trying to modify frozen item
        with raises(ValueError, match=r"(?i)cannot assign"):
            addonly_list[idx] = value
    else:  # Out of bounds
        with raises(IndexError):
            addonly_list[idx] = value


@given(
    items=string_lists,
    idx=indices,
)
def test_delitem(items: list[str], idx: int) -> None:
    """Test that `.delitem()` works correctly and handles errors."""
    addonly_list = FreezableList(items)

    frozen_size = len(items)

    if -frozen_size <= idx < frozen_size:  # In bounds
        # Should raise error when trying to delete frozen item
        with raises(ValueError, match=r"(?i)cannot delete"):
            del addonly_list[idx]
    else:  # Out of bounds
        with raises(IndexError):
            del addonly_list[idx]


@given(
    init_items=string_lists,
    index=indices,
    value=strings,
)
def test_insert(init_items: list[str], index: int, value: str) -> None:
    """Test that `.insert()` works correctly and handles errors."""
    addonly_list = FreezableList(init_items)
    frozen_size = len(init_items)

    # Duplicates should be silently ignored, no matter what
    if value in init_items:
        addonly_list.insert(index, value)
        assert value not in addonly_list._draft
        assert len(addonly_list) == frozen_size

    # In bounds, all items frozen:
    # Should raise error when trying to insert new items between/before frozen ones
    elif -frozen_size <= index < frozen_size:
        with raises(IndexError, match=r"(?i)cannot insert"):
            addonly_list.insert(index, value)

        assert value not in addonly_list._draft
        assert len(addonly_list) == frozen_size

    # Negative out of bounds, frozen items exist:
    # Should raise error when trying to insert new items before frozen ones
    elif (index < -frozen_size) and init_items:
        with raises(IndexError, match=r"(?i)cannot insert"):
            addonly_list.insert(index, value)

        assert value not in addonly_list._draft
        assert len(addonly_list) == frozen_size

    # Otherwise, item should be inserted into draft portion
    else:
        addonly_list.insert(index, value)
        assert value in addonly_list._draft
        assert len(addonly_list) == frozen_size + 1


@given(
    items=string_lists,
    other_item=strings,
)
def test_contains(items: list[str], other_item: str) -> None:
    """Test that `in`/`contains` works like a typical list."""
    addonly_list = FreezableList(items)
    normal_list = list(items)

    # Test items in the list
    for item in items:
        assert item in addonly_list
        assert item in normal_list

    # Test behavior of any other item, which may or may not be in the list
    assert (other_item in addonly_list) == (other_item in normal_list)


@given(items=string_lists)
def test_len(items: list[str]) -> None:
    """Test that len works like a typical list."""
    addonly_list = FreezableList(items)
    normal_list = list(items)

    assert len(addonly_list) == len(normal_list) == len(items)


@given(items=string_lists)
def test_iter(items: list[str]) -> None:
    """Test that iteration works like a typical list."""
    addonly_list = FreezableList(items)
    normal_list = list(items)

    for addonly_item, normal_item in zip_longest(addonly_list, normal_list):
        assert addonly_item == normal_item


@given(
    items=string_lists,
    slice_obj=slices(20),
)
def test_slice(items: list[str], slice_obj: slice) -> None:
    """Test that slicing works like a typical list."""

    normal_list = list(items)
    addonly_list = FreezableList(items)

    assert addonly_list[slice_obj] == normal_list[slice_obj]

    # For good measure, test slices generated via extended indexing syntax too
    assert list(addonly_list[:]) == normal_list[:]
    assert list(addonly_list[1:]) == normal_list[1:]
    assert list(addonly_list[:-1]) == normal_list[:-1]
    assert list(addonly_list[::2]) == normal_list[::2]
    assert list(addonly_list[::-1]) == normal_list[::-1]
