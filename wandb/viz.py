from wandb.data_types import Table
from wandb.errors import Error

class Visualize:
    def __init__(self, viz_id, value):
        self.viz_id = viz_id
        self.value = value

def visualize(viz_id, value):
    if not isinstance(value, Table):
        raise Error("visualize value must be Table, not {}".format(type(value).__name__))
    return Visualize(viz_id, value)

class CustomChart:
    def __init__(self, viz_id, table, config_mapping):
        self.viz_id = viz_id
        self.table = table
        self.panel_config = config_mapping

def create_custom_chart(vega_spec_name, data_table, config_mapping):
    if not isinstance(data_table, Table):
        raise Error("custom chart data_table must be Table, not {}".format(type(data_table).__name__))

    return CustomChart(vega_spec_name, data_table, config_mapping)

def update_custom_chart_panel_config(custom_chart, key):
    table_key = key + "_table"
    userQuery = {
        "userQuery": {
            "queryFields": [
                {
                    "name": "runSets",
                    "args": [
                        {
                            "name": "runSets",
                            "value": "${runSets}"
                        }
                    ],
                    "fields": [
                        {
                            "name": "name",
                            "fields": []
                        },
                        {
                            "name": "summaryTable",
                            "args": [
                                {
                                    "name": "tableKey",
                                    "value": table_key
                                }
                            ],
                            "fields": []
                        }
                    ]
                }
            ],
        }
    }
    
    custom_chart.panel_config.update({'panelDefId': custom_chart.viz_id})
    custom_chart.panel_config.update(
        {'transform': {"name": "tableWithLeafColNames"}}
    )
    custom_chart.panel_config.update(
        {"historyFieldSettings": {"key": table_key, "x-axis": "_step"}}
    )
    custom_chart.panel_config.update(userQuery)