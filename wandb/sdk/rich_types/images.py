from typing import Any, Sequence

from .image import Image
from .media_sequence import MediaSequence


class Images(MediaSequence[Any, Image]):
    OBJ_TYPE = "images/separated"
    DEFAULT_FORMAT = "PNG"

    def __init__(self, items: Sequence[Any]):
        super().__init__(items, Image)

    def to_json(self) -> dict:
        items = [item.to_json() for item in self._items]
        return {
            "_type": self.OBJ_TYPE,
            "width": max([item.get("width", 0) for item in items]),
            "height": max([item.get("height", 0) for item in items]),
            "count": len(items),
            "filenames": [item["path"] for item in items],
        }
