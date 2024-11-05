from __future__ import annotations

from typing import Any

import wandb


class CustomChart:
    def __init__(
        self,
        spec_name: str,
        data: wandb.Table,
        fields: dict[str, Any],
        string_fields: dict[str, Any],
        split_table: bool = False,
    ) -> None:
        self._spec_name = spec_name
        self._data = data
        self._fields = fields
        self._string_fields = string_fields
        self._split_table = split_table

    def get_config_value(
        self,
        panel_type: str,
        query: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "panel_type": panel_type,
            "panel_config": {
                "panelDefId": self._spec_name,
                "fieldSettings": self._fields,
                "stringSettings": self._string_fields,
                "transform": {"name": "tableWithLeafColNames"},
                "userQuery": query,
            },
        }

    @staticmethod
    def get_config_key(key: str) -> tuple[str, str, str]:
        return "_wandb", "visualize", key

    @staticmethod
    def user_query(table_key: str) -> dict[str, Any]:
        return {
            "queryFields": [
                {
                    "name": "runSets",
                    "args": [{"name": "runSets", "value": "${runSets}"}],
                    "fields": [
                        {"name": "id", "fields": []},
                        {"name": "name", "fields": []},
                        {"name": "_defaultColorIndex", "fields": []},
                        {
                            "name": "summaryTable",
                            "args": [{"name": "tableKey", "value": table_key}],
                            "fields": [],
                        },
                    ],
                }
            ],
        }

    @property
    def table(self) -> wandb.Table:
        return self._data

    @property
    def fields(self) -> dict[str, Any]:
        return self._fields

    @property
    def string_fields(self) -> dict[str, Any]:
        return self._string_fields


def plot_table(
    vega_spec_name: str,
    data_table: wandb.Table,
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
        data_table (wandb.Table): A `wandb.Table` object containing the data to be
            visualized.
        fields (dict[str, Any]): A mapping between the fields in the Vega-Lite spec and the
            corresponding columns in the data table to be visualized.
        string_fields (dict[str, Any] | None): A dictionary for providing values for any string constants
            required by the custom visualization.
        split_table (bool): If True, the table will be displayed in a separate
            section in the W&B UI. Default is False.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass it to `wandb.log()`.

    Raises:
        wandb.Error: If `data_table` is not a `wandb.Table` object.
    """

    if not isinstance(data_table, wandb.Table):
        raise wandb.Error(
            f"Expected `data_table` to be `wandb.Table` type, instead got {type(data_table).__name__}"
        )

    if string_fields is None:
        string_fields = {}

    return CustomChart(
        spec_name=vega_spec_name,
        data=data_table,
        fields=fields,
        string_fields=string_fields,
        split_table=split_table,
    )
