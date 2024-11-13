from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wandb.data_types import Table
from wandb.errors import Error


@dataclass
class VisualizeSpec:
    name: str
    key: str = ""

    @property
    def config_value(self) -> dict[str, Any]:
        return {
            "id": self.name,
            "historyFieldSettings": {"x-axis": "_step", "key": self.key},
        }

    @property
    def config_key(self) -> tuple[str, str, str]:
        return ("_wandb", "viz", self.key)


@dataclass
class Visualize:
    table: Table
    spec: VisualizeSpec

    def set_key(self, key: str) -> None:
        self.spec.key = key


def visualize(id: str, value: Table) -> Visualize:
    if not isinstance(value, Table):
        raise Error(
            f"Expected `value` to be `wandb.Table` type, instead got {type(value).__name__}"
        )
    return Visualize(table=value, spec=VisualizeSpec(name=id))
