from __future__ import annotations

from typing import Any

import wandb


class CustomChart:
    def __init__(
        self,
        id: str,
        data: wandb.Table,
        fields: dict[str, Any],
        string_fields: dict[str, Any],
        split_table: bool = False,
    ) -> None:
        self._id = id
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
                "panelDefId": self._id,
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
