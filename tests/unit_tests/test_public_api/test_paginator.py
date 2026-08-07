from __future__ import annotations

from collections.abc import Iterable, Sequence

import pytest
from wandb.apis.paginator import Paginator

ITEMS = ["a", "b", "c", "d", "e"]


class FakePaginator(Paginator[str]):
    """A paginator that serves a fixed list of objects, one page at a time."""

    QUERY = None

    def __init__(self, items: Sequence[str], per_page: int = 2):
        super().__init__(service_api=None, variables={}, per_page=per_page)
        self._items = list(items)
        self.pages_loaded = 0

    @property
    def more(self) -> bool:
        return len(self.objects) < len(self._items)

    @property
    def cursor(self) -> str | None:
        return str(len(self.objects))

    def _update_response(self) -> None:
        start = len(self.objects)
        self.last_response = self._items[start : start + self.per_page]
        self.pages_loaded += 1

    def convert_objects(self) -> Iterable[str]:
        return self.last_response


@pytest.mark.parametrize("index", [-1, -3, -len(ITEMS)])
def test_negative_index_on_unloaded_paginator(index: int):
    assert FakePaginator(ITEMS)[index] == ITEMS[index]


@pytest.mark.parametrize("index", [-1, -3, -len(ITEMS)])
def test_negative_index_on_partially_loaded_paginator(index: int):
    paginator = FakePaginator(ITEMS)
    assert paginator[0] == ITEMS[0]

    assert paginator[index] == ITEMS[index]


@pytest.mark.parametrize(
    "index",
    [
        slice(None, None),
        slice(2, None),
        slice(None, -1),
        slice(-2, None),
        slice(None, None, 2),
        slice(None, None, -1),
        slice(1, 3),
        slice(0, 100),
    ],
)
def test_slice_matches_list_slice(index: slice):
    assert FakePaginator(ITEMS)[index] == ITEMS[index]


def test_out_of_range_index_raises_index_error():
    with pytest.raises(IndexError):
        FakePaginator(ITEMS)[len(ITEMS)]

    with pytest.raises(IndexError):
        FakePaginator(ITEMS)[-len(ITEMS) - 1]


def test_bounded_index_only_loads_the_pages_it_needs():
    paginator = FakePaginator(ITEMS)

    assert paginator[1] == ITEMS[1]

    assert paginator.pages_loaded == 1
    assert paginator.more
