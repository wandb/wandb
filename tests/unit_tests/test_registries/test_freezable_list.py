import pytest
from wandb.apis.public.registries._freezable_list import FreezableList


@pytest.fixture
def empty_list() -> FreezableList[int]:
    return FreezableList[int]()


@pytest.fixture
def list_with_frozen() -> FreezableList[int]:
    return FreezableList[int]([1, 2, 3])


@pytest.fixture
def list_with_draft() -> FreezableList[int]:
    fl = FreezableList[int]()
    fl.append(4)
    fl.append(5)
    return fl


@pytest.fixture
def list_with_frozen_and_draft() -> FreezableList[int]:
    fl = FreezableList[int]([1, 2, 3])
    fl.append(4)
    fl.append(5)
    return fl


def test_init_empty():
    fl = FreezableList[str]()
    assert list(fl) == []
    assert len(fl) == 0
    assert fl._frozen == ()
    assert fl._draft == []


def test_init_with_iterable():
    initial_items = [10, 20, 30]
    fl = FreezableList[int](initial_items)
    assert list(fl) == initial_items
    assert len(fl) == len(initial_items)
    assert fl._frozen == tuple(initial_items)
    assert fl._draft == []


def test_append(empty_list: FreezableList[int]):
    empty_list.append(1)
    assert list(empty_list) == [1]
    assert len(empty_list) == 1
    assert empty_list._frozen == ()
    assert empty_list._draft == [1]

    empty_list.append(2)
    assert list(empty_list) == [1, 2]
    assert len(empty_list) == 2
    assert empty_list._frozen == ()
    assert empty_list._draft == [1, 2]


def test_append_duplicate_in_draft(list_with_draft: FreezableList[int]):
    list_with_draft.append(4)  # Duplicate in draft
    assert list(list_with_draft) == [4, 5]
    assert len(list_with_draft) == 2
    assert list_with_draft._draft == [4, 5]


def test_append_duplicate_in_frozen(list_with_frozen_and_draft: FreezableList[int]):
    list_with_frozen_and_draft.append(1)  # Duplicate in frozen
    assert list(list_with_frozen_and_draft) == [1, 2, 3, 4, 5]
    assert len(list_with_frozen_and_draft) == 5
    assert list_with_frozen_and_draft._draft == [4, 5]


def test_freeze_empty_draft(list_with_frozen: FreezableList[int]):
    original_frozen = list_with_frozen._frozen
    list_with_frozen.freeze()
    assert list_with_frozen._frozen == original_frozen
    assert list_with_frozen._draft == []
    assert list(list_with_frozen) == list(original_frozen)


def test_freeze_non_empty_draft(list_with_frozen_and_draft: FreezableList[int]):
    list_with_frozen_and_draft.freeze()
    assert list_with_frozen_and_draft._frozen == (1, 2, 3, 4, 5)
    assert list_with_frozen_and_draft._draft == []
    assert list(list_with_frozen_and_draft) == [1, 2, 3, 4, 5]
    assert len(list_with_frozen_and_draft) == 5


def test_freeze_with_duplicates_between_draft_and_frozen(
    list_with_frozen: FreezableList[int],
):
    list_with_frozen.append(1)  # Exists in frozen
    list_with_frozen.append(4)  # New
    list_with_frozen.append(2)  # Exists in frozen
    list_with_frozen.append(5)  # New

    assert list_with_frozen._draft == [1, 4, 2, 5]
    list_with_frozen.freeze()
    # Only non-duplicates (4, 5) should be added to frozen
    assert list_with_frozen._frozen == (1, 2, 3, 4, 5)
    assert list_with_frozen._draft == []
    assert list(list_with_frozen) == [1, 2, 3, 4, 5]


def test_remove_from_draft(list_with_frozen_and_draft: FreezableList[int]):
    fl = list_with_frozen_and_draft
    fl.remove(4)
    assert list(fl) == [1, 2, 3, 5]
    assert 4 not in fl._draft

    fl.remove(5)
    assert list(fl) == [1, 2, 3]
    assert fl._draft == []


def test_remove_errors(list_with_frozen_and_draft: FreezableList[int]):
    with pytest.raises(ValueError):  # list.remove raises ValueError
        list_with_frozen_and_draft.remove(100)
    with pytest.raises(ValueError, match="Cannot remove item from frozen list: 1"):
        list_with_frozen_and_draft.remove(1)


def test_contains(list_with_frozen_and_draft: FreezableList[int]):
    assert 1 in list_with_frozen_and_draft  # frozen
    assert 4 in list_with_frozen_and_draft  # draft
    assert 100 not in list_with_frozen_and_draft


def test_len(empty_list, list_with_frozen, list_with_draft, list_with_frozen_and_draft):
    assert len(empty_list) == 0
    assert len(list_with_frozen) == 3
    assert len(list_with_draft) == 2
    assert len(list_with_frozen_and_draft) == 5


def test_getitem_int(list_with_frozen_and_draft: FreezableList[int]):
    assert list_with_frozen_and_draft[2] == 3  # frozen
    assert list_with_frozen_and_draft[3] == 4  # draft
    assert list_with_frozen_and_draft[-1] == 5  # draft
    assert list_with_frozen_and_draft[-5] == 1  # frozen


def test_getitem_int_out_of_bounds(list_with_frozen_and_draft: FreezableList[int]):
    with pytest.raises(IndexError):
        _ = list_with_frozen_and_draft[5]
    with pytest.raises(IndexError):
        _ = list_with_frozen_and_draft[-6]


def test_getitem_slice(list_with_frozen_and_draft: FreezableList[int]):
    assert list_with_frozen_and_draft[:] == [1, 2, 3, 4, 5]
    assert list_with_frozen_and_draft[1:4] == [2, 3, 4]
    assert list_with_frozen_and_draft[:2] == [1, 2]  # frozen only
    assert list_with_frozen_and_draft[3:] == [4, 5]  # draft only
    assert list_with_frozen_and_draft[-3:] == [3, 4, 5]
    assert list_with_frozen_and_draft[::2] == [1, 3, 5]


def test_setitem_draft(list_with_frozen_and_draft: FreezableList[int]):
    fl = list_with_frozen_and_draft
    fl[3] = 40  # Update draft item
    assert list(fl) == [1, 2, 3, 40, 5]
    assert fl._draft == [40, 5]

    fl[-1] = 50  # Update draft item using negative index
    assert list(fl) == [1, 2, 3, 40, 50]
    assert fl._draft == [40, 50]


def test_setitem_duplicate(list_with_frozen_and_draft: FreezableList[int]):
    fl = list_with_frozen_and_draft
    fl[3] = 1  # Duplicate in frozen
    assert list(fl) == [1, 2, 3, 4, 5]  # No change
    assert fl._draft == [4, 5]

    fl[4] = 4  # Duplicate in draft
    assert list(fl) == [1, 2, 3, 4, 5]  # No change
    assert fl._draft == [4, 5]


def test_setitem_errors(list_with_frozen_and_draft: FreezableList[int]):
    with pytest.raises(IndexError):
        list_with_frozen_and_draft[5] = 50
    with pytest.raises(IndexError):
        list_with_frozen_and_draft[-6] = 60
    with pytest.raises(TypeError, match="Cannot assign to saved item at index 1"):
        list_with_frozen_and_draft[1] = 20
    with pytest.raises(
        TypeError, match="'FreezableList' does not support slice assignment"
    ):
        list_with_frozen_and_draft[1:3] = [10, 20]


def test_delitem_draft(list_with_frozen_and_draft: FreezableList[int]):
    fl = list_with_frozen_and_draft
    del fl[4]  # Delete last draft item
    assert list(fl) == [1, 2, 3, 4]
    assert fl._draft == [4]
    assert len(fl) == 4

    del fl[-1]  # Delete remaining draft item (index 3)
    assert list(fl) == [1, 2, 3]
    assert fl._draft == []
    assert len(fl) == 3


def test_delitem_errors(list_with_frozen_and_draft: FreezableList[int]):
    with pytest.raises(ValueError, match="Cannot delete saved item at index 0"):
        del list_with_frozen_and_draft[0]
    with pytest.raises(ValueError, match="Cannot delete saved item at index -5"):
        del list_with_frozen_and_draft[-5]
    with pytest.raises(IndexError):
        del list_with_frozen_and_draft[5]
    with pytest.raises(IndexError):
        del list_with_frozen_and_draft[-6]
    with pytest.raises(
        TypeError, match="'FreezableList' does not support slice deletion"
    ):
        del list_with_frozen_and_draft[3:]


def test_insert_into_draft(list_with_frozen_and_draft: FreezableList[int]):
    fl = list_with_frozen_and_draft
    # Insert at the beginning of draft (index 3)
    fl.insert(3, 35)
    assert list(fl) == [1, 2, 3, 35, 4, 5]
    assert fl._draft == [35, 4, 5]
    assert len(fl) == 6

    # Insert at the end of draft (index 6)
    fl.insert(6, 60)
    assert list(fl) == [1, 2, 3, 35, 4, 5, 60]
    assert fl._draft == [35, 4, 5, 60]
    assert len(fl) == 7

    # Insert in the middle of draft (index 5, which is -2 relative to end)
    fl.insert(-2, 45)
    assert list(fl) == [1, 2, 3, 35, 4, 45, 5, 60]
    assert fl._draft == [35, 4, 45, 5, 60]
    assert len(fl) == 8


def test_insert_duplicate(list_with_frozen_and_draft: FreezableList[int]):
    fl = list_with_frozen_and_draft
    len_before = len(fl)

    fl.insert(3, 1)  # Duplicate in frozen
    assert list(fl) == [1, 2, 3, 4, 5]
    assert fl._draft == [4, 5]
    assert len(fl) == len_before

    fl.insert(4, 4)  # Duplicate in draft
    assert list(fl) == [1, 2, 3, 4, 5]
    assert fl._draft == [4, 5]
    assert len(fl) == len_before


@pytest.mark.parametrize(
    "index_type",
    [
        "start_frozen",  # Beginning of frozen
        "end_frozen",  # End of frozen
        "negative_frozen",  # Negative index resolving into frozen
    ],
)
def test_insert_into_frozen_raises(
    list_with_frozen_and_draft: FreezableList[int], index_type: str
):
    if index_type == "start_frozen":
        invalid_index = 0
    elif index_type == "end_frozen":
        invalid_index = len(list_with_frozen_and_draft._frozen) - 1
    elif index_type == "negative_frozen":
        invalid_index = -len(list_with_frozen_and_draft) - 1

    with pytest.raises(IndexError, match="Cannot insert into the frozen list"):
        list_with_frozen_and_draft.insert(invalid_index, 99)
