from typing import Optional, Sequence

from .media import Media


class BatchableMedia(Media):
    def __init__(self, items: Sequence[Media]):
        self._items = items

    def bind_to_run(
        self, interface, start: pathlib.Path, *prefix, name: Optional[str] = None
    ) -> None:
        for item in self._items:
            item.bind_to_run(interface, start, *prefix, name=name)

    def to_json(self, namespace: Optional[str] = None) -> dict:
        return [item.to_json(namespace=namespace) for item in self._items]
