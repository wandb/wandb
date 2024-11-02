from __future__ import annotations

from typing import Any

from wandb.data_types import Table
from wandb.errors import Error


class Visualize:
    def __init__(self, id: str, data: Table) -> None:
        self._id = id
        self._data = data

    def get_config_value(self, key: str) -> dict[str, Any]:
        return {
            "id": self._id,
            "historyFieldSettings": {"x-axis": "_step", "key": key},
        }

    @staticmethod
    def get_config_key(key: str) -> tuple[str, str, str]:
        return "_wandb", "viz", key

    @property
    def value(self) -> Table:
        return self._data


def visualize(id: str, value: Table) -> Visualize:
    if not isinstance(value, Table):
        raise Error(
            f"Expected `value` to be `wandb.Table` type, instead got {type(value).__name__}"
        )
    return Visualize(id=id, data=value)
