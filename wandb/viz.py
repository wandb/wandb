from typing import Any, Dict, Tuple

from wandb.data_types import Table
from wandb.errors import Error


class Visualize:
    def __init__(self, id: str, data: Table) -> None:
        self._id = id
        self._data = data

    def get_config_value(self, key: str) -> Dict[str, Any]:
        return {
            "id": self._id,
            "historyFieldSettings": {"x-axis": "_step", "key": key},
        }

    @staticmethod
    def get_config_key(key: str) -> Tuple[str]:
        return ("_wandb", "viz", key)


class CustomChart:
    def __init__(
        self,
        id: str,
        data: Table,
        fields: Dict[str, Any],
        string_fields: Dict[str, Any],
    ) -> None:
        self._id = id
        self._data = data
        self._fields = fields
        self._string_fields = string_fields

    def get_config_value(
        self, panel_type: str, query: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "panel_type": panel_type,
            "panel_config": {
                "panelDefId": self._id,
                "fieldSettings": self._fields,
                "stringSettings": self._string_fields,
                "transform": {"name": "tableWithLeafColNames"},
                "userQuery": query,
            },
        }

    @staticmethod
    def get_config_key(key: str) -> Tuple[str]:
        return ("_wandb", "visualize", key)

    @staticmethod
    def user_query(table_key: str) -> Dict[str, Any]:
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


def plot_table(
    vega_spec_name: str,
    data_table: Table,
    fields: Dict[str, Any],
    string_fields: Dict[str, Any] = {},
) -> CustomChart:
    if not isinstance(data_table, Table):
        raise Error(
            f"Expected `data_table` to be `wandb.Table` type, instead got  {type(data_table).__name__}"
        )
    return CustomChart(
        id=vega_spec_name, data=data_table, fields=fields, string_fields=string_fields,
    )


def visualize(id: str, value: Table) -> Visualize:
    if not isinstance(value, Table):
        raise Error(
            f"Expected `value` to be `wandb.Table` type, instead got {type(value).__name__}"
        )
    return Visualize(id=id, data=value)
