import matplotlib
import numpy as np
import pytest
import wandb
from wandb import data_types
from wandb.sdk.data_types import _dtypes
from wandb.sdk.internal import incremental_table_util

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


@pytest.mark.parametrize("log_mode", ["IMMUTABLE", "MUTABLE", "INCREMENTAL"])
def test_table_logged_from_run_with_special_characters_in_name(
    user, test_settings, log_mode
):
    name_and_id = "random-run-id-=1234567-seed-0"  # Contains special characters

    with wandb.init(name=name_and_id, id=name_and_id) as run:
        table = wandb.Table(
            ["col1", "col2", "col3"],
            [[1, 4.6, "hello"], [5, 4.5, "world"]],
            allow_mixed_types=True,
            log_mode=log_mode,
        )
        run.log({"my-table": table}, step=1)


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


def test_incr_logging_initial_log(user, test_settings):
    run = wandb.init(settings=test_settings())
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})
    run.finish()
    api_run = wandb.Api().run(f"uncategorized/{run.id}")
    assert len(api_run.logged_artifacts()) == 1
    assert t._last_logged_idx == 0
    assert t._artifact_target is not None
    assert t._increment_num == 0


def test_incr_logging_add_data_reset_state_and_increment_counter(user, test_settings):
    run = wandb.init(settings=test_settings())
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})
    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    run.finish()
    # _increment_num should only be incremented after data is added
    assert t._artifact_target is None
    assert t._run is None
    assert t._sha256 is None
    assert t._path is None
    assert t._increment_num == 1
    assert len(t._previous_increments_paths) == 1


def test_incr_logging_multiple_logs(user, test_settings):
    """Test multiple logging operations on an incremental table."""
    run = wandb.init(settings=test_settings())
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")

    # Initial log
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})

    # Add more data and log again
    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})

    # Verify state after second log
    assert t._last_logged_idx == 2
    assert t._increment_num == 1
    assert len(t._previous_increments_paths) == 1

    # Add more data and log again
    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    run.log({"table": t})
    run.finish()

    # Verify state after third log
    assert t._last_logged_idx == 4
    assert t._increment_num == 2
    assert len(t._previous_increments_paths) == 2

    api_run = wandb.Api().run(f"uncategorized/{run.id}")
    assert len(api_run.logged_artifacts()) == 3


def test_using_incrementally_logged_table(user, test_settings, monkeypatch):
    # override get_entry_name to use deterministic timestamps
    log_count = 0

    def mock_get_entry_name(incr_table, key):
        nonlocal log_count
        entry_name = f"{log_count}-100000000{log_count}.{key}"
        log_count += 1
        return entry_name

    monkeypatch.setattr(
        "wandb.sdk.internal.incremental_table_util.get_entry_name", mock_get_entry_name
    )

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
    art = run2.use_artifact(
        f"{incremental_table_util._get_artifact_name(run, table_key)}:latest"
    )
    incremental_table = art.get(f"{log_count - 1}-100000000{log_count - 1}.{table_key}")

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

    We expect the incremental table to get the previous paths and
    increment num from the previously logged incremental table.
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

    assert len(t._previous_increments_paths) == 2
    assert t._increment_num == 2

    t.add_data("2", "second")
    resumed_run.log({"table": t})

    assert len(t._previous_increments_paths) == 3
    assert t._increment_num == 3


def test_resumed_run_nothing_prev_logged_to_key(user, test_settings):
    """
    Test that incremental tables log normally in a resumed run when
    logged to a key that hasn't been logged to yet.
    """
    run = wandb.init(settings=test_settings(), id="resume_test_2")
    run.log({"test": 0.5})
    run.finish()

    resumed_run = wandb.init(
        settings=test_settings(), id="resume_test_2", resume="must"
    )
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})

    # The increment should start at 0 because nothing was
    # logged on the key `table`
    assert t._increment_num == 0

    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})

    assert t._last_logged_idx == 1

    resumed_run.finish()
    api_run = wandb.Api().run(f"uncategorized/{resumed_run.id}")

    assert len(api_run.logged_artifacts()) == 2


def test_resumed_run_no_prev_incr_table_wbvalue(user, test_settings):
    """
    Test that incremental tables log normally in a resumed run even if
    they weren't previously logged
    """
    run = wandb.init(settings=test_settings(), id="resume_test_2")
    regular_table = wandb.Table()
    run.log({"test": 0.5, "table": regular_table})
    run.finish()

    resumed_run = wandb.init(
        settings=test_settings(), id="resume_test_2", resume="must"
    )
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})

    # The increment should start at 0 because the last _type
    # on the summary on key `table` is not an incr table.
    assert t._increment_num == 0

    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})
    t.add_data("No", "No", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})

    assert t._last_logged_idx == 3

    resumed_run.finish()
    api_run = wandb.Api().run(f"uncategorized/{resumed_run.id}")

    assert len(api_run.logged_artifacts()) == 4


def test_resumed_run_no_prev_incr_table_nonwbvalue(user, test_settings):
    """
    Test that incremental tables log normally in a resumed run even if
    they weren't previously logged
    """
    run = wandb.init(settings=test_settings(), id="resume_test_2")
    run.log({"test": 0.5, "table": 0.5})
    run.finish()

    resumed_run = wandb.init(
        settings=test_settings(), id="resume_test_2", resume="must"
    )
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})

    # The increment should start at 0 because the last value
    # on the summary on key `table` is not an incr table.
    assert t._increment_num == 0

    t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})
    t.add_data("No", "No", wandb.Image(np.ones(shape=(32, 32))))
    resumed_run.log({"table": t})

    assert t._last_logged_idx == 3

    resumed_run.finish()
    api_run = wandb.Api().run(f"uncategorized/{resumed_run.id}")

    assert len(api_run.logged_artifacts()) == 3


def test_resumed_run_incremental_table_ordering(user, test_settings, monkeypatch):
    """
    Test that incremental tables maintain proper ordering when:
    1. Initial run logs some data
    2. First resumed run logs more data
    3. Second resumed run logs even more data
    4. Another run uses the artifact and verifies data order
    """

    # override get_entry_name to use deterministic timestamps
    log_count = 0

    def mock_get_entry_name(incr_table, key):
        nonlocal log_count
        entry_name = f"{log_count}-100000000{log_count}.{key}"
        log_count += 1
        return entry_name

    monkeypatch.setattr(
        "wandb.sdk.internal.incremental_table_util.get_entry_name", mock_get_entry_name
    )

    # Initial run
    run = wandb.init(settings=test_settings(), id="resume_order_test")
    t = wandb.Table(columns=["step", "value"], log_mode="INCREMENTAL")

    # First increment
    t.add_data(0, "first")
    t.add_data(1, "second")
    run.log({"table": t})
    run.finish()

    # First resume
    resumed_run1 = wandb.init(
        settings=test_settings(), id="resume_order_test", resume="must"
    )
    t = wandb.Table(columns=["step", "value"], log_mode="INCREMENTAL")

    # Second increment
    t.add_data(2, "third")
    t.add_data(3, "fourth")
    resumed_run1.log({"table": t})
    resumed_run1.finish()

    # Second resume
    resumed_run2 = wandb.init(
        settings=test_settings(), id="resume_order_test", resume="must"
    )
    t = wandb.Table(columns=["step", "value"], log_mode="INCREMENTAL")

    # Third increment
    t.add_data(4, "fifth")
    t.add_data(5, "sixth")
    resumed_run2.log({"table": t})
    resumed_run2.finish()

    verification_run = wandb.init(settings=test_settings())
    art = verification_run.use_artifact(f"run-{resumed_run2.id}-incr-table:latest")

    expected_full_data = [
        [0, "first"],
        [1, "second"],
        [2, "third"],
        [3, "fourth"],
        [4, "fifth"],
        [5, "sixth"],
    ]

    incremental_table = art.get(f"{log_count - 1}-100000000{log_count - 1}.table")
    assert incremental_table.data == expected_full_data

    verification_run.finish()


def test_incremental_tables_cannot_be_logged_on_multiple_runs(
    test_settings,
):
    with wandb.init(settings=test_settings(), mode="offline") as run1:
        incr_table = wandb.Table(columns=["step", "value"], log_mode="INCREMENTAL")

        incr_table.add_data(0, "0")
        run1.log({"table": incr_table})
        incr_table.add_data(1, "1")
        run1.log({"table": incr_table})

    with wandb.init(settings=test_settings(), mode="offline") as run2:
        incr_table.add_data(2, "2")
        with pytest.raises(AssertionError):
            run2.log({"table": incr_table})
