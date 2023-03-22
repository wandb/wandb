from typing import Sequence

from .media import Media
from dataclasses import dataclass


@dataclass
class Class:
    id: int
    name: str


class Classes(Media):
    OBJ_TYPE: str = "classes"

    def __init__(self, data) -> None:
        super().__init__()
        if isinstance(data, Sequence):
            self.from_sequence(data)
        elif isinstance(data, dict):
            self.from_dict(data)
        else:
            raise ValueError(
                "Classes must be initialized with a sequence, dict, or Class"
            )

        self._class_labels = class_labels

    def to_json(self) -> dict:
        return {
            "_type": self.OBJ_TYPE,
            "class_set": self._class_labels,
        }
