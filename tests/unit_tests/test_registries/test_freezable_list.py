import pytest
from wandb.registries._freezable_list import FreezableList


@pytest.fixture
def empty_list() -> FreezableList[str]:
    return FreezableList[str]()


@pytest.fixture
def list_2_frozen() -> FreezableList[str]:
    return FreezableList[str](["frozen_one", "frozen_two", "frozen_three"])


@pytest.fixture
def list_2_drafts() -> FreezableList[str]:
    fl = FreezableList[str]()
    fl.append("draft_one")
    fl.append("draft_two")
    return fl


@pytest.fixture
def list_3_frozen_and_2_drafts() -> FreezableList[str]:
    fl = FreezableList[str](["frozen_one", "frozen_two", "frozen_three"])
    fl.append("draft_one")
    fl.append("draft_two")
    return fl


def test_init_empty():
    fl = FreezableList[str]()
    assert list(fl) == []
    assert len(fl) == 0
    assert fl._frozen == ()
    assert fl._draft == []


def test_init_with_iterable():
    initial_items = ["date", "elderberry", "fig"]
    fl = FreezableList[str](initial_items)
    assert list(fl) == initial_items
    assert len(fl) == len(initial_items)
    assert fl._frozen == tuple(initial_items)
    assert fl._draft == []


def test_append(empty_list: FreezableList[str]):
    empty_list.append("new_item1")
    assert list(empty_list) == ["new_item1"]
    assert len(empty_list) == 1
    assert empty_list._frozen == ()
    assert empty_list._draft == ["new_item1"]

    empty_list.append("new_item2")
    assert list(empty_list) == ["new_item1", "new_item2"]
    assert len(empty_list) == 2
    assert empty_list._frozen == ()
    assert empty_list._draft == ["new_item1", "new_item2"]


def test_append_duplicate_list(list_3_frozen_and_2_drafts: FreezableList[str]):
    list_3_frozen_and_2_drafts.append("frozen_one")  # Duplicate in frozen
    assert list(list_3_frozen_and_2_drafts) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_one",
        "draft_two",
    ]
    assert list_3_frozen_and_2_drafts._draft == ["draft_one", "draft_two"]
    list_3_frozen_and_2_drafts.append("draft_one")  # Duplicate in draft
    assert list(list_3_frozen_and_2_drafts) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_one",
        "draft_two",
    ]
    assert list_3_frozen_and_2_drafts._draft == ["draft_one", "draft_two"]


def test_freeze_with_duplicates_between_draft_and_frozen(
    list_3_frozen_and_2_drafts: FreezableList[str],
):
    list_3_frozen_and_2_drafts.append("frozen_one")  # Exists in frozen
    list_3_frozen_and_2_drafts.append("draft_one")  # Duplicate in draft
    list_3_frozen_and_2_drafts.append("new_item")  # New

    assert list_3_frozen_and_2_drafts._draft == [
        "draft_one",
        "draft_two",
        "new_item",
    ]
    list_3_frozen_and_2_drafts.freeze()
    # Only non-duplicate ("new_item") should be added to frozen
    assert list_3_frozen_and_2_drafts._frozen == tuple(
        list_3_frozen_and_2_drafts._frozen
    ) + tuple(list_3_frozen_and_2_drafts._draft)
    assert list_3_frozen_and_2_drafts._draft == []


def test_remove_from_draft(list_3_frozen_and_2_drafts: FreezableList[str]):
    fl = list_3_frozen_and_2_drafts
    fl.remove("draft_one")
    assert list(fl) == ["frozen_one", "frozen_two", "frozen_three", "draft_two"]
    assert fl._draft == ["draft_two"]

    fl.remove("draft_two")
    assert list(fl) == ["frozen_one", "frozen_two", "frozen_three"]
    assert fl._draft == []


def test_remove_errors(list_3_frozen_and_2_drafts: FreezableList[str]):
    with pytest.raises(ValueError):  # list.remove raises ValueError
        list_3_frozen_and_2_drafts.remove("non_existent")
    with pytest.raises(ValueError, match="Cannot remove item from frozen list"):
        list_3_frozen_and_2_drafts.remove("frozen_one")


def test_contains(list_3_frozen_and_2_drafts: FreezableList[str]):
    assert "frozen_one" in list_3_frozen_and_2_drafts  # frozen
    assert "draft_one" in list_3_frozen_and_2_drafts  # draft
    assert "non_existent" not in list_3_frozen_and_2_drafts


def test_len(
    empty_list: FreezableList[str],
    list_2_frozen: FreezableList[str],
    list_2_drafts: FreezableList[str],
    list_3_frozen_and_2_drafts: FreezableList[str],
):
    assert len(empty_list) == 0
    assert len(list_2_frozen) == 3
    assert len(list_2_drafts) == 2
    assert len(list_3_frozen_and_2_drafts) == 5


def test_getitem_int(list_3_frozen_and_2_drafts: FreezableList[str]):
    assert list_3_frozen_and_2_drafts[2] == "frozen_three"  # exists in frozen
    assert list_3_frozen_and_2_drafts[3] == "draft_one"  # exists in draft
    assert list_3_frozen_and_2_drafts[-1] == "draft_two"  # exists in draft
    assert list_3_frozen_and_2_drafts[-5] == "frozen_one"  # exists in frozen


def test_getitem_int_out_of_bounds(list_3_frozen_and_2_drafts: FreezableList[str]):
    list_len = len(list_3_frozen_and_2_drafts)
    with pytest.raises(IndexError):
        _ = list_3_frozen_and_2_drafts[list_len]
    with pytest.raises(IndexError):
        _ = list_3_frozen_and_2_drafts[-list_len - 1]


def test_getitem_slice(list_3_frozen_and_2_drafts: FreezableList[str]):
    fl = list_3_frozen_and_2_drafts
    assert list(fl[:]) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_one",
        "draft_two",
    ]
    assert list(fl[1:4]) == [
        "frozen_two",
        "frozen_three",
        "draft_one",
    ]
    assert list(fl[:2]) == ["frozen_one", "frozen_two"]  # frozen only
    assert list(fl[3:]) == ["draft_one", "draft_two"]  # draft only
    assert list(fl[-3:]) == ["frozen_three", "draft_one", "draft_two"]
    assert list(fl[::2]) == [
        "frozen_one",
        "frozen_three",
        "draft_two",
    ]


def test_setitem_draft(list_3_frozen_and_2_drafts: FreezableList[str]):
    fl = list_3_frozen_and_2_drafts
    fl[3] = "draft_updated"  # Update draft item
    assert list(fl) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_updated",
        "draft_two",
    ]
    assert fl._draft == ["draft_updated", "draft_two"]

    fl[-1] = "draft_two_updated"  # Update draft item using negative index
    assert list(fl) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_updated",
        "draft_two_updated",
    ]
    assert fl._draft == ["draft_updated", "draft_two_updated"]


def test_setitem_duplicate(list_3_frozen_and_2_drafts: FreezableList[str]):
    fl = list_3_frozen_and_2_drafts
    fl[3] = "frozen_one"  # Duplicate in frozen
    assert list(fl) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_one",
        "draft_two",
    ]  # No change
    assert fl._draft == ["draft_one", "draft_two"]

    fl[4] = "draft_one"  # Duplicate in draft
    assert list(fl) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_one",
        "draft_two",
    ]  # No change
    assert fl._draft == ["draft_one", "draft_two"]


def test_setitem_errors(list_3_frozen_and_2_drafts: FreezableList[str]):
    fl = list_3_frozen_and_2_drafts
    with pytest.raises(IndexError):
        fl[5] = "error_val"
    with pytest.raises(IndexError):
        fl[-6] = "error_val2"
    with pytest.raises(ValueError, match="Cannot assign to saved item at index 1"):
        fl[1] = "frozen_update"
    with pytest.raises(
        TypeError, match="'FreezableList' does not support slice assignment"
    ):
        fl[1:3] = ["new1", "new2"]


def test_delitem_draft(list_3_frozen_and_2_drafts: FreezableList[str]):
    fl = list_3_frozen_and_2_drafts
    del fl[4]  # Delete last draft item ("draft_two")
    assert list(fl) == ["frozen_one", "frozen_two", "frozen_three", "draft_one"]
    assert fl._draft == ["draft_one"]
    assert len(fl) == 4

    del fl[-1]  # Delete remaining draft item ("draft_one" at index 3)
    assert list(fl) == ["frozen_one", "frozen_two", "frozen_three"]
    assert fl._draft == []
    assert len(fl) == 3


def test_delitem_errors(list_3_frozen_and_2_drafts: FreezableList[str]):
    list_len = len(list_3_frozen_and_2_drafts)
    fl = list_3_frozen_and_2_drafts
    with pytest.raises(ValueError, match="Cannot delete saved item at index 0"):
        del fl[0]
    with pytest.raises(ValueError, match="Cannot delete saved item at index -5"):
        del fl[-list_len]
    with pytest.raises(IndexError):
        del fl[list_len]
    with pytest.raises(IndexError):
        del fl[-list_len - 1]
    with pytest.raises(
        TypeError, match="'FreezableList' does not support slice deletion"
    ):
        del fl[3:]


def test_insert_into_draft(list_3_frozen_and_2_drafts: FreezableList[str]):
    fl = list_3_frozen_and_2_drafts
    # Insert at the beginning of draft (index 3)
    fl.insert(3, "inserted_one")
    assert list(fl) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "inserted_one",
        "draft_one",
        "draft_two",
    ]
    assert fl._draft == ["inserted_one", "draft_one", "draft_two"]
    assert len(fl) == 6

    # Insert at the end of draft (index 6)
    fl.insert(6, "inserted_two")
    assert list(fl) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "inserted_one",
        "draft_one",
        "draft_two",
        "inserted_two",
    ]
    assert fl._draft == ["inserted_one", "draft_one", "draft_two", "inserted_two"]
    assert len(fl) == 7

    # Insert in the middle of draft (index 5, which is -2 relative to end)
    fl.insert(-2, "inserted_three")
    assert list(fl) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "inserted_one",
        "draft_one",
        "inserted_three",
        "draft_two",
        "inserted_two",
    ]
    assert fl._draft == [
        "inserted_one",
        "draft_one",
        "inserted_three",
        "draft_two",
        "inserted_two",
    ]
    assert len(fl) == 8


def test_insert_duplicate(list_3_frozen_and_2_drafts: FreezableList[str]):
    len_before = len(list_3_frozen_and_2_drafts)

    list_3_frozen_and_2_drafts.insert(3, "frozen_one")  # Duplicate in frozen
    assert list(list_3_frozen_and_2_drafts) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_one",
        "draft_two",
    ]
    assert list_3_frozen_and_2_drafts._draft == ["draft_one", "draft_two"]
    assert len(list_3_frozen_and_2_drafts) == len_before

    list_3_frozen_and_2_drafts.insert(5, "draft_one")  # Duplicate in draft
    assert list(list_3_frozen_and_2_drafts) == [
        "frozen_one",
        "frozen_two",
        "frozen_three",
        "draft_one",
        "draft_two",
    ]
    assert list_3_frozen_and_2_drafts._draft == ["draft_one", "draft_two"]
    assert len(list_3_frozen_and_2_drafts) == len_before


@pytest.mark.parametrize(
    "index_type",
    [
        "start_frozen",  # Beginning of frozen
        "end_frozen",  # End of frozen
        "negative_frozen",  # Negative index resolving into frozen
    ],
)
def test_insert_into_frozen_raises(
    list_3_frozen_and_2_drafts: FreezableList[str], index_type: str
):
    if index_type == "start_frozen":
        invalid_index = 0
    elif index_type == "end_frozen":
        invalid_index = len(list_3_frozen_and_2_drafts._frozen) - 1
    elif index_type == "negative_frozen":
        invalid_index = -len(list_3_frozen_and_2_drafts)  # Index for "frozen_one"

    with pytest.raises(IndexError, match="Cannot insert into the frozen list"):
        list_3_frozen_and_2_drafts.insert(invalid_index, "invalid_insert")
