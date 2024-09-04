import json

import matplotlib
import numpy as np
import pytest
import wandb
from wandb.sdk.data_types import WBValue, data_types

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

    wbvalue = WBValue()
    with pytest.raises(NotImplementedError):
        wbvalue.to_json(local_art)

    with pytest.raises(NotImplementedError):
        WBValue.from_json({}, public_art)

    assert WBValue.with_suffix("item") == "item.json"

    table = WBValue.init_from_json(
        {
            "_type": "table",
            "data": [[]],
            "columns": [],
            "column_types": data_types._dtypes.TypedDictType({}).to_json(),
        },
        public_art,
    )
    assert isinstance(table, WBValue) and isinstance(table, wandb.Table)

    type_mapping = WBValue.type_mapping()
    assert all([issubclass(type_mapping[key], WBValue) for key in type_mapping])

    assert wbvalue == wbvalue
    assert wbvalue != WBValue()
    run.finish()


def test_log_dataframe(user, test_settings):
    import pandas as pd

    run = wandb.init(settings=test_settings())
    cv_results = pd.DataFrame(data={"test_col": [1, 2, 3], "test_col2": [4, 5, 6]})
    run.log({"results_df": cv_results})
    run.finish()

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert len(run.logged_artifacts()) == 1


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
