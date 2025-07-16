from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import wandb


@dataclass
class CustomChartSpec:
    spec_name: str
    fields: dict[str, Any]
    string_fields: dict[str, Any]
    key: str = ""
    panel_type: str = "Vega2"
    split_table: bool = False

    @property
    def table_key(self) -> str:
        if not self.key:
            raise wandb.Error("Key for the custom chart spec is not set.")
        if self.split_table:
            return f"Custom Chart Tables/{self.key}_table"
        return f"{self.key}_table"

    @property
    def config_value(self) -> dict[str, Any]:
        return {
            "panel_type": self.panel_type,
            "panel_config": {
                "panelDefId": self.spec_name,
                "fieldSettings": self.fields,
                "stringSettings": self.string_fields,
                "transform": {"name": "tableWithLeafColNames"},
                "userQuery": {
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
                                    "args": [
                                        {
                                            "name": "tableKey",
                                            "value": self.table_key,
                                        }
                                    ],
                                    "fields": [],
                                },
                            ],
                        }
                    ],
                },
            },
        }

    @property
    def config_key(self) -> tuple[str, str, str]:
        return ("_wandb", "visualize", self.key)


@dataclass
class CustomChart:
    table: wandb.Table
    spec: CustomChartSpec

    def set_key(self, key: str):
        """Sets the key for the spec and updates dependent configurations."""
        self.spec.key = key


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
    chart object that can be logged to W&B using `wandb.Run.log()`.

    Args:
        vega_spec_name: The name or identifier of the Vega-Lite spec
            that defines the visualization structure.
        data_table: A `wandb.Table` object containing the data to be
            visualized.
        fields: A mapping between the fields in the Vega-Lite spec and the
            corresponding columns in the data table to be visualized.
        string_fields: A dictionary for providing values for any string constants
            required by the custom visualization.
        split_table: Whether the table should be split into a separate section
            in the W&B UI. If `True`, the table will be displayed in a section named
            "Custom Chart Tables". Default is `False`.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass the chart object as argument to `wandb.Run.log()`.

    Raises:
        wandb.Error: If `data_table` is not a `wandb.Table` object.

    Example:
    ```python
    # Create a custom chart using a Vega-Lite spec and the data table.
    import wandb

    data = [[1, 1], [2, 2], [3, 3], [4, 4], [5, 5]]
    table = wandb.Table(data=data, columns=["x", "y"])
    fields = {"x": "x", "y": "y", "title": "MY TITLE"}

    with wandb.init() as run:
        # Training code goes here

        # Create a custom title with `string_fields`.
        my_custom_chart = wandb.plot_table(
            vega_spec_name="wandb/line/v0",
            data_table=table,
            fields=fields,
            string_fields={"title": "Title"},
        )

        run.log({"custom_chart": my_custom_chart})
    ```
    """

    if not isinstance(data_table, wandb.Table):
        raise wandb.Error(
            f"Expected `data_table` to be `wandb.Table` type, instead got {type(data_table).__name__}"
        )

    return CustomChart(
        table=data_table,
        spec=CustomChartSpec(
            spec_name=vega_spec_name,
            fields=fields,
            string_fields=string_fields or {},
            split_table=split_table,
        ),
    )
