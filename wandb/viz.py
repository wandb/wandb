from wandb.data_types import Table
from wandb.errors import Error


class Visualize:
    def __init__(self, viz_id, value):
        self.viz_id = viz_id
        self.value = value


def visualize(viz_id, value):
    if not isinstance(value, Table):
        raise Error(
            "visualize value must be Table, not {}".format(type(value).__name__)
        )
    return Visualize(viz_id, value)


class CustomChart:
    def __init__(self, viz_id, table, fields, string_fields):
        self.viz_id = viz_id
        self.table = table
        self.fields = fields
        self.string_fields = string_fields


def create_custom_chart(vega_spec_name, data_table, fields, string_fields):
    if not isinstance(data_table, Table):
        raise Error(
            "custom chart data_table must be Table, not {}".format(
                type(data_table).__name__
            )
        )

    return CustomChart(vega_spec_name, data_table, fields, string_fields)


def custom_chart_panel_config(custom_chart, key, table_key):
    userQuery = {
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

    return {
        "userQuery": userQuery,
        "panelDefId": custom_chart.viz_id,
        "transform": {"name": "tableWithLeafColNames"},
        "fieldSettings": custom_chart.fields,
        "stringSettings": custom_chart.string_fields,
    }
