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


def test_table_mutation_logging(user, test_settings, wandb_backend_spy):
    run = wandb.init(settings=test_settings())
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="MUTABLE")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})
    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})
    t.get_column("expected")
    run.log({"table": t})
    run.finish()

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert len(run.logged_artifacts()) == 3


def test_table_incremental_logging(user, test_settings, wandb_backend_spy):
    run = wandb.init(settings=test_settings())
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})
    assert t._last_logged_idx == 0
    assert t._artifact_target is not None
    assert t._increment_num == 0
    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    # _increment_num is only incremented after data is added
    assert t._artifact_target is None
    assert t._increment_num == 1
    assert len(t._previous_increments_paths) == 1
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})
    assert t._last_logged_idx == 2
    assert t._increment_num == 1
    t.add_data("No", "No", wandb.Image(np.ones(shape=(32, 32))))
    assert t._last_logged_idx == 2
    assert t._increment_num == 2
    assert len(t._previous_increments_paths) == 2
    run.log({"table": t})
    assert t._last_logged_idx == 3
    run.finish()
    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert len(run.logged_artifacts()) == 3


def test_using_incrementally_logged_table(user, test_settings, wandb_backend_spy):
    table_key = "test"
    run = wandb.init(settings=test_settings())
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({table_key: t})
    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    run.log({table_key: t})
    run.finish()

    run2 = wandb.init(settings=test_settings())
    art = run2.use_artifact(f"run-{run.id}-incr-{table_key}:latest")
    incremental_table = art.get(f"1.{table_key}.table.json")
    assert len(incremental_table.data) == 3
    assert incremental_table.log_mode == "INCREMENTAL"
    assert incremental_table.columns == ["expected", "actual", "img"]


def test_table_incremental_logging_empty(user, test_settings, wandb_backend_spy):
    """Test that empty incremental tables are handled correctly."""
    run = wandb.init(settings=test_settings())
    t = wandb.Table(columns=["a", "b"], log_mode="INCREMENTAL")
    run.log({"table": t})  # Should handle empty table
    t.add_data("1", "first")
    run.log({"table": t})  # Should log first increment
    run.finish()
    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert len(run.logged_artifacts()) == 2


def test_resumed_run_incremental_table(user, test_settings):
    """
    Test that incremental tables are logged correctly from a resumed run.
    """
    run = wandb.init(settings=test_settings(), id="resume_test")
    t = wandb.Table(columns=["a", "b"], log_mode="INCREMENTAL")
    run.log({"table": t})
    t.add_data("1", "first")
    run.log({"table": t})
    run.finish()

    resumed_run = wandb.init(settings=test_settings(), id="resume_test", resume="must")
    t = wandb.Table(columns=["a", "b"], log_mode="INCREMENTAL")
    resumed_run.log({"table": t})
    assert t._resume_handled
    assert len(t._previous_increments_paths) == 2
    assert t._increment_num == 2

    t.add_data("2", "second")
    resumed_run.log({"table": t})
    assert len(t._previous_increments_paths) == 3
    assert t._increment_num == 3


def test_resumed_run_no_prev_incr_table(user, test_settings):
    """
    Test that incremental tables log normally in a resumed run even if
    they weren't previously logged
    """
    run = wandb.init(settings=test_settings(), id="resume_test_2")
    run.finish()

    resumed_run = wandb.init(
        settings=test_settings(), id="resume_test_2", resume="must"
    )
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})
    assert t._resume_handled
    assert t._last_logged_idx == 0
    assert t._artifact_target is not None
    assert t._increment_num == 0
    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    # _increment_num is only incremented after data is added
    assert t._artifact_target is None
    assert t._increment_num == 1
    assert len(t._previous_increments_paths) == 1
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})
    assert t._last_logged_idx == 2
    assert t._increment_num == 1
    t.add_data("No", "No", wandb.Image(np.ones(shape=(32, 32))))
    assert t._last_logged_idx == 2
    assert t._increment_num == 2
    assert len(t._previous_increments_paths) == 2
    resumed_run.log({"table": t})
    assert t._last_logged_idx == 3
    resumed_run.finish()
    api_run = wandb.Api().run(f"uncategorized/{resumed_run.id}")
    assert len(api_run.logged_artifacts()) == 3


def test_resumed_run_multi_types_on_key(user, test_settings):
    """
    Test that the incremental table for this scenario:
    1. User logs an incremental table to key A
    2. User logs something else to key A
    3. Run finishes
    4. Run resumes
    5. User logs an incremental table to key A
    """
    run = wandb.init(settings=test_settings(), id="resume_test_3")
    # User logs an incremental table to key `table`
    incr_table = wandb.Table(
        columns=["expected", "actual", "img"], log_mode="INCREMENTAL"
    )
    incr_table.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": incr_table})
    incr_table.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": incr_table})
    # User logs something else to key `table`
    immutable_table = wandb.Table(columns=["expected", "actual", "img"])
    immutable_table.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": immutable_table})
    run.finish()

    resumed_run = wandb.init(
        settings=test_settings(), id="resume_test_3", resume="must"
    )
    # User logs an incremental table to key `table`
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})
    assert t._resume_handled
    assert t._resume_random_id is not None
    assert t._last_logged_idx == 0
    assert t._artifact_target is not None
    assert t._increment_num == 0
    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    assert t._artifact_target is None
    assert t._increment_num == 1
    assert len(t._previous_increments_paths) == 1
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})
    assert t._last_logged_idx == 2
    assert t._increment_num == 1
    resumed_run.finish()
    api_run = wandb.Api().run(f"uncategorized/{resumed_run.id}")
    assert len(api_run.logged_artifacts()) == 5

    manifest_entries = api_run.logged_artifacts()[4].manifest.entries
    expected_entries = [
        f"0-{t._resume_random_id}.table.table.json",
        f"1-{t._resume_random_id}.table.table.json",
    ]
    for entry in expected_entries:
        assert entry in manifest_entries
