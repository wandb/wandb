import json
import math
import random

import matplotlib
import numpy as np
import pytest
import wandb
from wandb import data_types

matplotlib.use("Agg")

data = np.random.randint(255, size=(1000))


@pytest.fixture
def sample_data():
    artifact = wandb.Artifact("N", type="dataset")
    artifact.save()


def test_wb_value(user, sample_data, test_settings):
    run = wandb.init(settings=test_settings())
    local_art = wandb.Artifact("N", "T")
    public_art = run.use_artifact("N:latest")

    wbvalue = data_types.WBValue()
    with pytest.raises(NotImplementedError):
        wbvalue.to_json(local_art)

    with pytest.raises(NotImplementedError):
        data_types.WBValue.from_json({}, public_art)

    assert data_types.WBValue.with_suffix("item") == "item.json"

    table = data_types.WBValue.init_from_json(
        {
            "_type": "table",
            "data": [[]],
            "columns": [],
            "column_types": wandb.data_types._dtypes.TypedDictType({}).to_json(),
        },
        public_art,
    )
    assert isinstance(table, data_types.WBValue) and isinstance(
        table, wandb.data_types.Table
    )

    type_mapping = data_types.WBValue.type_mapping()
    assert all(
        [issubclass(type_mapping[key], data_types.WBValue) for key in type_mapping]
    )

    assert wbvalue == wbvalue
    assert wbvalue != data_types.WBValue()
    run.finish()


def test_log_dataframe(user, test_settings):
    import pandas as pd

    run = wandb.init(settings=test_settings())
    cv_results = pd.DataFrame(data={"test_col": [1, 2, 3], "test_col2": [4, 5, 6]})
    run.log({"results_df": cv_results})
    run.finish()

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert len(run.logged_artifacts()) == 1


def test_log_nested_cc(user, test_settings, relay_server, inject_graphql_response):
    server_info_response = inject_graphql_response(
        # request
        query_match_fn=lambda query, variables: query.startswith("query ServerInfo"),
        # response
        body=json.dumps(
            {"data": {"serverInfo": {"cliVersionInfo": {"max_cli_version": "0.11.0"}}}}
        ),
    )
    with relay_server(inject=[server_info_response]):
        run = wandb.init(settings=test_settings())
        x_data = [0, 1, 2, 3, 4]
        y_data = [[123, 333, 111, 42, 533], [0.5, 11, 72, 3, 41]]
        run.log(
            {
                "layer1": {
                    "level4": wandb.plot.line_series(
                        xs=x_data, ys=y_data, keys=["metric_A", "metric_B"]
                    )
                }
            }
        )
        run.finish()


def test_log_nested_split_table(
    user, test_settings, relay_server, inject_graphql_response
):
    server_info_response = inject_graphql_response(
        # request
        query_match_fn=lambda query, variables: query.startswith("query ServerInfo"),
        # response
        body=json.dumps(
            {"data": {"serverInfo": {"cliVersionInfo": {"max_cli_version": "0.11.0"}}}}
        ),
    )
    with relay_server(inject=[server_info_response]):
        run = wandb.init(settings=test_settings())
        offset = random.random()
        # Set up data to log in custom charts
        randomized_data = []
        # log 5 different randomized plots
        for k in range(5):
            data = []
            for i in range(100):
                data.append(
                    [
                        i,
                        random.random() + math.log(1 + i) + offset + random.random(),
                    ]
                )
            randomized_data.append(data)

            # Create a table with the columns to plot
            table = wandb.Table(data=randomized_data[k], columns=["step", "height"])

            # Map from the table's columns to the chart's fields
            fields = {"x": "step", "value": "height"}

            # Use the table to populate the new custom chart preset
            # To use your own saved chart preset, change the vega_spec_name
            my_custom_chart = wandb.plot_table(
                vega_spec_name="carey/new_chart",
                data_table=table,
                fields=fields,
                split_table=True,
            )

            # Log the plot to have it show up in the UI
            run.log({f"test{k}": {"test2": my_custom_chart}})
        run.finish()


def test_log_nested_visualize(
    user, test_settings, relay_server, inject_graphql_response
):
    server_info_response = inject_graphql_response(
        # request
        query_match_fn=lambda query, variables: query.startswith("query ServerInfo"),
        # response
        body=json.dumps(
            {"data": {"serverInfo": {"cliVersionInfo": {"max_cli_version": "0.11.0"}}}}
        ),
    )
    with relay_server(inject=[server_info_response]):
        run = wandb.init(settings=test_settings())
        data = [
            ("Dog", "Dog", 34),
            ("Cat", "Cat", 29),
            ("Dog", "Cat", 5),
            ("Cat", "Dog", 3),
            ("Bird", "Bird", 40),
            ("Bird", "Cat", 2),
        ]

        table = wandb.Table(columns=["Predicted", "Actual", "Count"], data=data)

        run.log(
            {"test": {"test2": wandb.visualize("wandb/confusion_matrix/v1", table)}}
        )
        run.finish()


@pytest.mark.parametrize("max_cli_version", ["0.10.33", "0.11.0"])
def test_reference_table_logging(
    user, test_settings, relay_server, inject_graphql_response, max_cli_version
):
    server_info_response = inject_graphql_response(
        # request
        query_match_fn=lambda query, variables: query.startswith("query ServerInfo"),
        # response
        body=json.dumps(
            {
                "data": {
                    "serverInfo": {
                        "cliVersionInfo": {"max_cli_version": max_cli_version}
                    }
                }
            }
        ),
    )
    with relay_server(inject=[server_info_response]):
        run = wandb.init(settings=test_settings())
        t = wandb.Table(
            columns=["a"],
            data=[[wandb.Image(np.ones(shape=(32, 32)))]],
        )
        run.log({"logged_table": t})
        run.log({"logged_table": t})
        run.finish()


def test_reference_table_artifacts(
    user, test_settings, relay_server, inject_graphql_response
):
    server_info_response = inject_graphql_response(
        # request
        query_match_fn=lambda query, variables: query.startswith("query ServerInfo"),
        # response
        body=json.dumps(
            {"data": {"serverInfo": {"cliVersionInfo": {"max_cli_version": "0.11.0"}}}}
        ),
    )
    with relay_server(inject=[server_info_response]):
        run = wandb.init(settings=test_settings())
        t = wandb.Table(
            columns=["a"],
            data=[[wandb.Image(np.ones(shape=(32, 32)))]],
        )

        art = wandb.Artifact("A", "dataset")
        art.add(t, "table")
        run.log_artifact(art)
        art = wandb.Artifact("A", "dataset")
        art.add(t, "table")
        run.log_artifact(art)

        run.finish()
