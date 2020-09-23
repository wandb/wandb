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
    def __init__(self, panel_config):
        self.panel_config = panel_config

def custom_plot_on_table(vega_spec_name, table_key, config_mapping):
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

    panel_config = {}
    panel_config.update(config_mapping)
    panel_config.update({'panelDefId': vega_spec_name})
    panel_config.update(
        {'transform': {"name": "tableWithLeafColNames"}}
    )
    panel_config.update(
        {"historyFieldSettings": {"key": table_key, "x-axis": "_step"}}
    )
    panel_config.update(userQuery)
    return CustomChart(panel_config)
