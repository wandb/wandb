import matplotlib
import numpy as np
import pytest
import wandb
from wandb import data_types

matplotlib.use("Agg")

data = np.random.randint(255, size=(1000))


def test_wb_value(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
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


def test_log_dataframe(live_mock_server, test_settings):
    import pandas as pd

    run = wandb.init(settings=test_settings)
    cv_results = pd.DataFrame(data={"test_col": [1, 2, 3], "test_col2": [4, 5, 6]})
    run.log({"results_df": cv_results})
    run.finish()
    ctx = live_mock_server.get_ctx()
    assert len(ctx["artifacts"]) == 1


@pytest.mark.parametrize("max_cli_version", ["0.10.33", "0.11.0"])
def test_reference_table_logging(
    mocked_run, live_mock_server, test_settings, reinit_internal_api, max_cli_version
):
    live_mock_server.set_ctx({"max_cli_version": max_cli_version})
    run = wandb.init(settings=test_settings)
    t = wandb.Table(
        columns=["a"],
        data=[[wandb.Image(np.ones(shape=(32, 32)))]],
    )
    run.log({"logged_table": t})
    run.log({"logged_table": t})
    run.finish()
    assert True


def test_reference_table_artifacts(
    mocked_run, live_mock_server, test_settings, reinit_internal_api
):
    live_mock_server.set_ctx({"max_cli_version": "0.11.0"})
    run = wandb.init(settings=test_settings)
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
    assert True
