import matplotlib
import numpy as np
import pytest
import wandb
from wandb import data_types
from wandb.sdk.data_types import _dtypes

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
            "column_types": _dtypes.TypedDictType({}).to_json(),
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


@pytest.mark.parametrize("max_cli_version", ["0.10.33", "0.11.0"])
def test_reference_table_logging(
    user, test_settings, wandb_backend_spy, max_cli_version
):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerInfo"),
        gql.once(
            content={
                "data": {
                    "serverInfo": {
                        "cliVersionInfo": {"max_cli_version": max_cli_version}
                    }
                }
            },
            status=200,
        ),
    )

    run = wandb.init(settings=test_settings())
    t = wandb.Table(
        columns=["a"],
        data=[[wandb.Image(np.ones(shape=(32, 32)))]],
    )
    run.log({"logged_table": t})
    run.log({"logged_table": t})
    run.finish()


def test_reference_table_artifacts(user, test_settings, wandb_backend_spy):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerInfo"),
        gql.once(
            content={
                "data": {
                    "serverInfo": {"cliVersionInfo": {"max_cli_version": "0.11.0"}}
                }
            },
            status=200,
        ),
    )

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
