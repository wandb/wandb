from __future__ import annotations

from typing import Any

import wandb
from wandb.data_types import Table
from wandb.errors import Error
from wandb.plot.custom_chart import CustomChart


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


def plot_table(
    vega_spec_name: str,
    data_table: Table,
    fields: dict[str, Any],
    string_fields: dict[str, Any] | None = None,
    split_table: bool = False,
) -> CustomChart:
    """Creates a custom charts using a Vega-Lite specification and a `wandb.Table`.

    This function creates a custom chart based on a Vega-Lite specification and
    a data table represented by a `wandb.Table` object. The specification needs
    to be predefined and stored in the W&B backend. The function returns a custom
    chart object that can be logged to W&B using `wandb.log()`.

    Args:
        vega_spec_name (str): The name or identifier of the Vega-Lite spec
            that defines the visualization structure.
        data_table (Table): A `wandb.Table` object containing the data to be
            visualized.
        fields (dict[str, Any]): A mapping between the fields in the Vega-Lite spec and the
            corresponding columns in the data table to be visualized.
        string_fields: A dictionary for providing values for any string constants
            required by the custom visualization.
        split_table: If True, the table will be displayed in a separate
            section in the W&B UI. Default is False.

    Returns:
        A CustomChart object that can be logged to W&B using wandb.log()

    Raises:
        wandb.Error: If `data_table` is not a `wandb.Table` object.
    """

    if not isinstance(data_table, Table):
        raise wandb.Error(
            f"Expected `data_table` to be `wandb.Table` type, instead got {type(data_table).__name__}"
        )

    if string_fields is None:
        string_fields = {}

    return CustomChart(
        id=vega_spec_name,
        data=data_table,
        fields=fields,
        string_fields=string_fields,
        split_table=split_table,
    )
