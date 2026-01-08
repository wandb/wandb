from __future__ import annotations

from itertools import chain
from typing import Any, Iterable, Iterator, MutableSequence, Sequence, TypeVar, overload

from typing_extensions import Never

from wandb._strutils import nameof

T = TypeVar("T")


class FreezableList(MutableSequence[T]):
    """A list-like container type that only allows adding new items.

    It tracks "saved" (immutable) and "draft" (mutable) items.
    Items can be added, inserted, and removed while in draft state, but once frozen,
    they become immutable. Unlike a set, duplicate items are allowed in the draft
    state but duplicates already present in the saved state cannot be added.
    Any initial items passed to the constructor are saved.
    """

    def __init__(self, iterable: Iterable[T] | None = None, /) -> None:
        self._saved: tuple[T, ...] = tuple(iterable or ())
        self._draft: list[T] = []

    def append(self, value: T) -> None:
        """Append an item to the draft list. No duplicates are allowed."""
        if value not in self:
            self._draft.append(value)

    def remove(self, value: T) -> None:
        """Remove the first occurrence of value from the draft list."""
        if value in self._saved:
            raise ValueError(f"Cannot remove saved item from list: {value!r}")
        self._draft.remove(value)

    def freeze(self) -> None:
        """Freeze any draft items by adding them to the saved tuple."""
        # Filter out duplicates already in saved before extending
        self._saved = (
            *self._saved,
            *(obj for obj in self._draft if obj not in self._saved),
        )
        self._draft.clear()

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, Sequence):
            return NotImplemented
        return list(self) == list(value)

    def __contains__(self, value: Any) -> bool:
        return value in self._saved or value in self._draft

    def __len__(self) -> int:
        return len(self._saved) + len(self._draft)

    def __iter__(self) -> Iterator[T]:
        return iter(chain(self._saved, self._draft))

    @overload
    def __getitem__(self, index: int) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> MutableSequence[T]: ...

    def __getitem__(self, index: int | slice) -> T | MutableSequence[T]:
        return [*self._saved, *self._draft][index]  # type: ignore[return-value]

    @overload
    def __setitem__(self, index: int, value: T) -> None: ...
    @overload
    def __setitem__(self, index: slice, value: Iterable[T]) -> Never: ...

    def __setitem__(self, index: int | slice, value: Any) -> None:
        if isinstance(index, slice):
            # Setting slices might affect saved items, disallow for simplicity
            raise TypeError(f"{nameof(type(self))!r} does not support slice assignment")

        if value in self:
            return

        # The saved items are sequentially first and protected from changes
        size = len(self)
        if not (-size <= index < size):
            raise IndexError("Index out of range")

        draft_index = (index % size) - len(self._saved)
        if draft_index < 0:
            raise ValueError(f"Cannot assign to saved item at index {index!r}")
        self._draft[draft_index] = value

    @overload
    def __delitem__(self, index: int) -> None: ...
    @overload
    def __delitem__(self, index: slice) -> Never: ...

    def __delitem__(self, index: int | slice) -> None:
        if isinstance(index, slice):
            raise TypeError(f"{nameof(type(self))!r} does not support slice deletion")

        # The saved items are sequentially first and protected from changes
        size = len(self)
        if not (-size <= index < size):
            raise IndexError("Index out of range")

        draft_index = (index % size) - len(self._saved)
        if draft_index < 0:
            raise ValueError(f"Cannot delete saved item at index {index!r}")
        del self._draft[draft_index]

    def insert(self, index: int, value: T) -> None:
        """Insert item before index.

        Insertion is only allowed at indices corresponding to the draft portion
        of the list (i.e., index >= len(saved_items)). Negative indices are
        interpreted relative to the combined length of saved and draft items.
        """
        if value in self:
            # Silently ignore duplicates, similar to append
            return

        # The saved items are sequentially first and protected from changes
        size = len(self)

        # Follow `list.insert()`'s behavior when the index is out of bounds.
        # - Negative out-of-bounds index: prepend (only works if saved items
        #   are empty).
        if index < -size and not self._saved:
            return self._draft.insert(0, value)

        # - positive out-of-bounds index: append.
        if index >= size:
            return self._draft.append(value)

        # - in-bounds index: insert only if into the draft portion.
        draft_index = (index % size) - len(self._saved)
        if draft_index < 0:
            msg = f"Cannot insert into the saved list (index < {len(self._saved)})"
            raise IndexError(msg)
        return self._draft.insert(draft_index, value)

    def __repr__(self) -> str:
        return f"{nameof(type(self))}(saved={list(self._saved)!r}, draft={list(self._draft)!r})"

    @property
    def draft(self) -> tuple[T, ...]:
        """A read-only, tuple copy of the current draft items."""
        return tuple(self._draft)


class AddOnlyArtifactTypesList(FreezableList[str]):
    def remove(self, value: str) -> None:
        try:
            super().remove(value)
        except ValueError:
            msg = f"Cannot remove artifact type {value!r} that has been saved to the registry"
            raise ValueError(msg) from None
