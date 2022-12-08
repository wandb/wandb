from .base import BaseObject
from typing import Sequence


class Classes(BaseObject):
    OBJ_TYPE: str = "classes"

    def __init__(self, class_labels: Sequence[dict]) -> None:

        self._class_labels = class_labels

    def to_json(self) -> dict:
        return {
            "_type": self.OBJ_TYPE,
            "class_set": self._class_labels,
        }
