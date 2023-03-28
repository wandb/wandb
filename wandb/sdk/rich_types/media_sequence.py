import pathlib
from typing import Generic, Sequence, Type, TypeVar

T = TypeVar("T")
U = TypeVar("U")


class MediaSequence(Generic[T, U]):
    def __init__(self, items: Sequence[T], item_type: Type[U]):
        self._items = [item_type(item) for item in items]

    def bind_to_run(
        self,
        interface,
        root_dir: pathlib.Path,
        *namespace: Sequence[str],
    ) -> None:
        for item in self._items:
            item.bind_to_run(interface, root_dir, *namespace)  # type: ignore

    def to_json(self) -> dict:
        ...
