from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import matplotlib
import numpy as np
import wandb
from pytest import MonkeyPatch, fixture, mark, raises
from typing_extensions import TypeAlias
from wandb import Api
from wandb.data_types import Table, WBValue
from wandb.sdk.data_types._dtypes import TypedDictType
from wandb.sdk.internal import incremental_table_util

if TYPE_CHECKING:
    from tests.fixtures.wandb_backend_spy import WandbBackendSpy

matplotlib.use("Agg")

data = np.random.randint(255, size=(1000))

SettingsFactory: TypeAlias = Callable[..., wandb.Settings]


def filter_artifacts_by_type(run, *artifact_types):
    """Filter logged artifacts by their type(s).

    Do NOT assert on length of run.logged_artifacts().
    Server side can generate other artifacts e.g. parquet exports.

    Args:
        run: The wandb API run object.
        *artifact_types: One or more artifact type strings to filter by.

    Returns:
        List of artifacts matching the specified type(s).
    """
    return [art for art in run.logged_artifacts() if art.type in artifact_types]


@fixture
def sample_data(user: str) -> None:
    # NOTE: Requesting the `user` fixture is important as it sets auth
    # environment variables for the duration of the test.
    _ = user

    artifact = wandb.Artifact("N", type="dataset")
    artifact.save()


@mark.usefixtures("sample_data")
def test_wb_value(test_settings: SettingsFactory):
    with wandb.init(settings=test_settings()) as run:
        local_art = wandb.Artifact("N", "T")
        public_art = run.use_artifact("N:latest")

        wbvalue = WBValue()
        with raises(NotImplementedError):
            wbvalue.to_json(local_art)

        with raises(NotImplementedError):
            WBValue.from_json({}, public_art)

        assert WBValue.with_suffix("item") == "item.json"

        table = WBValue.init_from_json(
            {
                "_type": "table",
                "data": [[]],
                "columns": [],
                "column_types": TypedDictType({}).to_json(),
            },
            public_art,
        )
        assert isinstance(table, WBValue) and isinstance(table, Table)

        type_mapping = WBValue.type_mapping()
        assert all([issubclass(type_mapping[key], WBValue) for key in type_mapping])

        assert wbvalue == wbvalue
        assert wbvalue != WBValue()


def test_log_dataframe(user: str, api: Api, test_settings: SettingsFactory):
    import pandas as pd

    with wandb.init(settings=test_settings()) as run:
        cv_results = pd.DataFrame(data={"test_col": [1, 2, 3], "test_col2": [4, 5, 6]})
        run.log({"results_df": cv_results})

    api_run = api.run(f"uncategorized/{run.id}")
    table_artifacts = filter_artifacts_by_type(api_run, "run_table")
    assert len(table_artifacts) == 1


@mark.parametrize("log_mode", ["IMMUTABLE", "MUTABLE", "INCREMENTAL"])
def test_table_logged_from_run_with_special_characters_in_name(
    user: str, log_mode: str
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


@mark.parametrize("max_cli_version", ["0.10.33", "0.11.0"])
def test_reference_table_logging(
    user: str,
    test_settings: SettingsFactory,
    wandb_backend_spy: WandbBackendSpy,
    max_cli_version: str,
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

    with wandb.init(settings=test_settings()) as run:
        t = wandb.Table(
            columns=["a"],
            data=[[wandb.Image(np.ones(shape=(32, 32)))]],
        )
        run.log({"logged_table": t})
        run.log({"logged_table": t})


def test_reference_table_artifacts(
    user: str,
    test_settings: SettingsFactory,
    wandb_backend_spy: WandbBackendSpy,
):
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

    with wandb.init(settings=test_settings()) as run:
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


def test_table_mutation_logging(user: str, api: Api, test_settings: SettingsFactory):
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="MUTABLE")
    with wandb.init(settings=test_settings()) as run:
        t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
        run.log({"table": t})
        t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
        run.log({"table": t})
        t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
        run.log({"table": t})
        t.get_column("expected")
        run.log({"table": t})

    api_run = api.run(f"uncategorized/{run.id}")
    table_artifacts = filter_artifacts_by_type(api_run, "run_table")
    assert len(table_artifacts) == 3


def test_incr_logging_initial_log(user: str, api: Api, test_settings: SettingsFactory):
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    with wandb.init(settings=test_settings()) as run:
        t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
        run.log({"table": t})

    api_run = api.run(f"uncategorized/{run.id}")
    table_artifacts = filter_artifacts_by_type(api_run, "wandb-run-incremental-table")
    assert len(table_artifacts) == 1
    assert t._last_logged_idx == 0
    assert t._artifact_target is not None
    assert t._increment_num == 0


def test_incr_logging_add_data_reset_state_and_increment_counter(
    user: str,
    test_settings: SettingsFactory,
):
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    with wandb.init(settings=test_settings()) as run:
        t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
        run.log({"table": t})
        t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))

    # _increment_num should only be incremented after data is added
    assert t._artifact_target is None
    assert t._run is None
    assert t._sha256 is None
    assert t._path is None
    assert t._increment_num == 1
    assert len(t._previous_increments_paths) == 1


def test_incr_logging_multiple_logs(user: str, test_settings, api: Api):
    """Test multiple logging operations on an incremental table."""
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    with wandb.init(settings=test_settings()) as run:
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

    # Verify state after third log
    assert t._last_logged_idx == 4
    assert t._increment_num == 2
    assert len(t._previous_increments_paths) == 2

    api_run = api.run(f"uncategorized/{run.id}")
    table_artifacts = filter_artifacts_by_type(api_run, "wandb-run-incremental-table")
    assert len(table_artifacts) == 3


def test_using_incrementally_logged_table(
    user: str,
    test_settings: SettingsFactory,
    monkeypatch: MonkeyPatch,
):
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
    t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
    with wandb.init(settings=test_settings()) as run:
        t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
        run.log({table_key: t})
        t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
        t.add_data("No", "Yes", wandb.Image(np.ones(shape=(32, 32))))
        run.log({table_key: t})

    with wandb.init(settings=test_settings()) as run2:
        art = run2.use_artifact(
            f"{incremental_table_util._get_artifact_name(run, table_key)}:latest"
        )
        incremental_table = art.get(
            f"{log_count - 1}-100000000{log_count - 1}.{table_key}"
        )

        assert len(incremental_table.data) == 3
        assert incremental_table.log_mode == "INCREMENTAL"
        assert incremental_table.columns == ["expected", "actual", "img"]


def test_table_incremental_logging_empty(
    user: str,
    test_settings: SettingsFactory,
    api: Api,
):
    """Test that empty incremental tables are handled correctly."""
    t = wandb.Table(columns=["a", "b"], log_mode="INCREMENTAL")
    with wandb.init(settings=test_settings()) as run:
        run.log({"table": t})  # Should handle empty table
        t.add_data("1", "first")
        run.log({"table": t})  # Should log first increment

    api_run = api.run(f"uncategorized/{run.id}")

    table_artifacts = filter_artifacts_by_type(api_run, "wandb-run-incremental-table")
    assert len(table_artifacts) == 2


def test_resumed_run_incremental_table(user: str, test_settings: SettingsFactory):
    """
    Test that incremental tables are logged correctly from a resumed run.

    We expect the incremental table to get the previous paths and
    increment num from the previously logged incremental table.
    """
    with wandb.init(settings=test_settings(), id="resume_test") as run:
        t = wandb.Table(columns=["a", "b"], log_mode="INCREMENTAL")
        run.log({"table": t})
        t.add_data("1", "first")
        run.log({"table": t})

    with wandb.init(
        settings=test_settings(), id="resume_test", resume="must"
    ) as resumed_run:
        t = wandb.Table(columns=["a", "b"], log_mode="INCREMENTAL")
        resumed_run.log({"table": t})

        assert len(t._previous_increments_paths) == 2
        assert t._increment_num == 2

        t.add_data("2", "second")
        resumed_run.log({"table": t})

        assert len(t._previous_increments_paths) == 3
        assert t._increment_num == 3


def test_resumed_run_nothing_prev_logged_to_key(
    user: str,
    test_settings: SettingsFactory,
    api: Api,
):
    """
    Test that incremental tables log normally in a resumed run when
    logged to a key that hasn't been logged to yet.
    """
    with wandb.init(settings=test_settings(), id="resume_test_2") as run:
        run.log({"test": 0.5})

    with wandb.init(
        settings=test_settings(), id="resume_test_2", resume="must"
    ) as resumed_run:
        t = wandb.Table(columns=["expected", "actual", "img"], log_mode="INCREMENTAL")
        t.add_data("Yes", "No", wandb.Image(np.ones(shape=(32, 32))))
        resumed_run.log({"table": t})

        # The increment should start at 0 because nothing was
        # logged on the key `table`
        assert t._increment_num == 0

        t.add_data("Yes", "Yes", wandb.Image(np.ones(shape=(32, 32))))
        resumed_run.log({"table": t})

        assert t._last_logged_idx == 1

    api_run = api.run(f"uncategorized/{resumed_run.id}")

    table_artifacts = filter_artifacts_by_type(api_run, "wandb-run-incremental-table")
    assert len(table_artifacts) == 2


def test_resumed_run_no_prev_incr_table_wbvalue(
    user: str,
    test_settings: SettingsFactory,
    api: Api,
):
    """
    Test that incremental tables log normally in a resumed run even if
    they weren't previously logged
    """
    with wandb.init(settings=test_settings(), id="resume_test_2") as run:
        regular_table = wandb.Table()
        run.log({"test": 0.5, "table": regular_table})

    with wandb.init(
        settings=test_settings(), id="resume_test_2", resume="must"
    ) as resumed_run:
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

    api_run = api.run(f"uncategorized/{resumed_run.id}")

    table_artifacts = filter_artifacts_by_type(
        api_run, "run_table", "wandb-run-incremental-table"
    )
    assert len(table_artifacts) == 4


def test_resumed_run_no_prev_incr_table_nonwbvalue(
    user: str,
    test_settings: SettingsFactory,
    api: Api,
):
    """
    Test that incremental tables log normally in a resumed run even if
    they weren't previously logged
    """
    with wandb.init(settings=test_settings(), id="resume_test_2") as run:
        run.log({"test": 0.5, "table": 0.5})

    with wandb.init(
        settings=test_settings(), id="resume_test_2", resume="must"
    ) as resumed_run:
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

    api_run = api.run(f"uncategorized/{resumed_run.id}")

    table_artifacts = filter_artifacts_by_type(api_run, "wandb-run-incremental-table")
    assert len(table_artifacts) == 3


def test_resumed_run_incremental_table_ordering(
    user: str,
    test_settings: SettingsFactory,
    monkeypatch: MonkeyPatch,
):
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
    with wandb.init(settings=test_settings(), id="resume_order_test") as run:
        t = wandb.Table(columns=["step", "value"], log_mode="INCREMENTAL")

        # First increment
        t.add_data(0, "first")
        t.add_data(1, "second")
        run.log({"table": t})

    # First resume
    with wandb.init(
        settings=test_settings(), id="resume_order_test", resume="must"
    ) as resumed_run1:
        t = wandb.Table(columns=["step", "value"], log_mode="INCREMENTAL")

        # Second increment
        t.add_data(2, "third")
        t.add_data(3, "fourth")
        resumed_run1.log({"table": t})

    # Second resume
    with wandb.init(
        settings=test_settings(), id="resume_order_test", resume="must"
    ) as resumed_run2:
        t = wandb.Table(columns=["step", "value"], log_mode="INCREMENTAL")

        # Third increment
        t.add_data(4, "fifth")
        t.add_data(5, "sixth")
        resumed_run2.log({"table": t})

    with wandb.init(settings=test_settings()) as verification_run:
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


def test_incremental_tables_cannot_be_logged_on_multiple_runs(
    test_settings: SettingsFactory,
):
    with wandb.init(settings=test_settings(), mode="offline") as run1:
        incr_table = wandb.Table(columns=["step", "value"], log_mode="INCREMENTAL")

        incr_table.add_data(0, "0")
        run1.log({"table": incr_table})
        incr_table.add_data(1, "1")
        run1.log({"table": incr_table})

    with wandb.init(settings=test_settings(), mode="offline") as run2:
        incr_table.add_data(2, "2")
        with raises(AssertionError):
            run2.log({"table": incr_table})
