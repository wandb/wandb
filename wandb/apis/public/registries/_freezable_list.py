from itertools import chain
from typing import (
    Any,
    Generic,
    Iterable,
    Iterator,
    List,
    MutableSequence,
    Sequence,
    Tuple,
    TypeVar,
    Union,
    final,
    overload,
)

T = TypeVar("T")


@final
class FreezableList(MutableSequence[T], Generic[T]):
    """A list-like container type that only allows adding new items.

    It tracks "saved" (immutable) and "draft" (mutable) items.
    Items can be added, inserted, and removed while in draft state, but once frozen,
    they become immutable. Unlike a set, duplicate items are allowed in the draft
    state but duplicates already present in the saved state cannot be added.
    Any initial items passed to the constructor are saved.
    """

    def __init__(self, iterable: Union[Iterable[T], None] = None, /) -> None:
        self._frozen: Tuple[T, ...] = tuple(iterable or ())
        self._draft: List[T] = []

    def append(self, value: T) -> None:
        """Append an item to the draft list. No duplicates are allowed."""
        if value in self._frozen or value in self._draft:
            return
        self._draft.append(value)

    def remove(self, value: T) -> None:
        """Remove the first occurrence of value from the draft list."""
        if value in self._frozen:
            raise ValueError(f"Cannot remove item from frozen list: {value!r}")
        self._draft.remove(value)

    def freeze(self) -> None:
        """Freeze any draft items by adding them to the saved tuple."""
        # Filter out duplicates already in saved before extending
        new_items = tuple(item for item in self._draft if item not in self._frozen)
        self._frozen = self._frozen + new_items
        self._draft.clear()

    def __contains__(self, value: Any) -> bool:
        return value in self._frozen or value in self._draft

    def __len__(self) -> int:
        return len(self._frozen) + len(self._draft)

    def __iter__(self) -> Iterator[T]:
        return iter(chain(self._frozen, self._draft))

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[T]: ...

    def __getitem__(self, index: Union[int, slice]) -> Union[T, Sequence[T]]:
        combined = list(self._frozen) + self._draft
        return combined[index]

    @overload
    def __setitem__(self, index: int, value: T) -> None: ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[T]) -> None: ...

    def __setitem__(
        self, index: Union[int, slice], value: Union[T, Iterable[T]]
    ) -> None:
        if isinstance(index, slice):
            # Setting slices might affect saved items, disallow for simplicity
            raise TypeError("'FreezableList' does not support slice assignment")
        else:
            if value in self._frozen or value in self._draft:
                return

            len_saved = len(self._frozen)
            original_index = index

            if index < 0:
                index += len(self)

            if 0 <= index < len_saved:
                raise TypeError(
                    f"Cannot assign to saved item at index {original_index}"
                )
            elif len_saved <= index < len(self):
                draft_index = index - len_saved
                self._draft[draft_index] = value
            else:
                raise IndexError("Index out of range")

    @overload
    def __delitem__(self, index: int) -> None: ...

    @overload
    def __delitem__(self, index: slice) -> None: ...

    def __delitem__(self, index: Union[int, slice]) -> None:
        if isinstance(index, slice):
            raise TypeError("'FreezableList' does not support slice deletion")
        else:
            len_saved = len(self._frozen)
            original_index = index

            if index < 0:
                index += len(self)

            if 0 <= index < len_saved:
                raise ValueError(f"Cannot delete saved item at index {original_index}")
            elif len_saved <= index < len(self):
                draft_index = index - len_saved
                del self._draft[draft_index]
            else:
                raise IndexError("Index out of range")

    def insert(self, index: int, value: T) -> None:
        """Insert item before index.

        Insertion is only allowed at indices corresponding to the draft portion
        of the list (i.e., index >= len(frozen_items)). Negative indices are
        interpreted relative to the combined length of frozen and draft items.
        """
        if value in self._frozen or value in self._draft:
            # Silently ignore duplicates, similar to append
            return

        len_frozen = len(self._frozen)

        if index < 0:
            index += len(self)

        if index < len_frozen:
            raise IndexError(
                f"Cannot insert into the frozen list (index < {len_frozen})"
            )

        draft_index = index - len_frozen

        self._draft.insert(draft_index, value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(frozen={list(self._frozen)!r}, draft={list(self._draft)!r})"

    @property
    def draft(self) -> Tuple[T, ...]:
        """A read-only, tuple copy of the current draft items."""
        return tuple(self._draft)


class AddOnlyArtifactTypesList(FreezableList[str]):
    def remove(self, value: str) -> None:
        try:
            super().remove(value)
        except ValueError:
            raise ValueError(
                f"Cannot remove artifact type: {value!r} that has been saved to the registry"
            )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(saved={list(self._frozen)!r}, draft={list(self._draft)!r})"
