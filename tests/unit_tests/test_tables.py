import datetime
import json

import numpy as np
import pytest
import wandb
from wandb.sdk.data_types.table import _ForeignKeyType, _PrimaryKeyType


def test_basic_ndx():
    # Base Case
    table_a = wandb.Table(columns=["b"], data=[["a"], ["b"]])
    table = wandb.Table(columns=["fi", "c"])
    for _ndx, _ in table_a.iterrows():
        table.add_data(_ndx, "x")
    assert all([row[0]._table == table_a for row in table.data])

    # Adding is supported
    table.add_data(3, "c")
    # Adding duplicates is supported
    table.add_data(3, "c")
    # Adding None isn't supported
    with pytest.raises(TypeError):
        table.add_data(None, "d")

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == [0, 1, 3, 3]
    assert all([row[0] is None or row[0]._table == table_a for row in table.data])


def test_pk_cast(use_helper=False):
    # Base Case
    table = wandb.Table(columns=["id", "b"], data=[["1", "a"], ["2", "b"]])

    # Validate that iterrows works as intended for no pks
    assert [id_ for id_, row in list(table.iterrows())] == [0, 1]

    # Cast as a PK
    if use_helper:
        table.set_pk("id")
    else:
        table.cast("id", _PrimaryKeyType())

    assert all(
        [row[0]._table == table and row[0]._col_name == "id" for row in table.data]
    )

    # Adding is supported
    table.add_data("3", "c")

    # Adding Duplicates fail
    # TODO: Enforce duplicate (not supported today)
    # with pytest.raises(TypeError):
    #     table.add_data("3", "d")

    # Adding None should fail
    with pytest.raises(TypeError):
        table.add_data(None, "d")

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == ["1", "2", "3"]
    assert all(row[0]._table == table for row in table.data)
    assert isinstance(
        table._column_types.params["type_map"]["id"],
        _PrimaryKeyType,
    )

    # Assert that multiple PKs are not supported
    with pytest.raises(AssertionError):
        if use_helper:
            table.set_pk("b")
        else:
            table.cast("b", _PrimaryKeyType())

    # Fails on Numerics for now
    table = wandb.Table(columns=["id", "b"], data=[[1, "a"], [2, "b"]])
    with pytest.raises(TypeError):
        if use_helper:
            table.set_pk("id")
        else:
            table.cast("id", _PrimaryKeyType())

    # Assert that the table was not modified
    assert all([row[0].__class__ is int for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["id"],
        _PrimaryKeyType,
    )

    # TODO: Test duplicates (not supported today)
    # Fails on initial duplicates
    # table = wandb.Table(columns=["id", "b"], data=[["1", "a"], ["1", "b"]])
    # with pytest.raises(TypeError):
    #     if use_helper:
    #         table.set_pk("id")
    #     else:
    #         table.cast("id", wandb.data_types._PrimaryKeyType())

    # # Assert that the table was not modified
    # assert all([row[0].__class__ == str for row in table.data])
    # assert not isinstance(
    #     table._column_types.params["type_map"]["id"],wandb.data_types._ForeignKeyType
    # )


def test_pk_helper():
    test_pk_cast(use_helper=True)


def test_fk_cast(use_helper=False):
    # Base Case
    table_a = wandb.Table(columns=["id", "col_1"], data=[["1", "a"], ["2", "b"]])
    table_a.set_pk("id")

    table = wandb.Table(columns=["fk", "col_2"], data=[["1", "c"], ["2", "d"]])

    # Cast as a FK
    if use_helper:
        table.set_fk("fk", table_a, "id")
    else:
        table.cast("fk", _ForeignKeyType(table_a, "id"))

    # Adding is supported
    table.add_data("3", "c")

    # Adding Duplicates is supported
    table.add_data("3", "d")

    # TODO: Implement constraint to only allow valid keys

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == ["1", "2", "3", "3"]
    assert all(
        [row[0]._table == table_a and row[0]._col_name == "id" for row in table.data]
    )
    assert isinstance(
        table._column_types.params["type_map"]["fk"],
        _ForeignKeyType,
    )

    # Fails on Numerics for now
    table = wandb.Table(columns=["fk", "col_2"], data=[[1, "c"], [2, "d"]])
    with pytest.raises(TypeError):
        if use_helper:
            table.set_fk("fk", table_a, "id")
        else:
            table.cast("fk", _ForeignKeyType(table_a, "id"))

    # Assert that the table was not modified
    assert all([row[0].__class__ is int for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["fk"],
        _ForeignKeyType,
    )


def test_fk_helper():
    test_fk_cast(use_helper=True)


def test_fk_from_pk_local_draft():
    table_a = wandb.Table(columns=["id", "col_1"], data=[["1", "a"], ["2", "b"]])
    table_a.set_pk("id")

    table = wandb.Table(
        columns=["fk", "col_2"], data=[[table_a.data[0][0], "c"], ["2", "d"]]
    )
    table.add_data("3", "c")

    # None should not be supported
    with pytest.raises(TypeError):
        table.add_data(None, "c")

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == ["1", "2", "3"]
    assert all(
        [
            row[0] is None or (row[0]._table == table_a and row[0]._col_name == "id")
            for row in table.data
        ]
    )

    table = wandb.Table(columns=["fk", "col_2"], data=[["1", "c"], ["2", "d"]])
    table.add_data(table_a.data[0][0], "c")
    with pytest.raises(TypeError):
        table.add_data(None, "c")

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == ["1", "2", "1"]
    assert all(
        [
            row[0] is None or (row[0]._table == table_a and row[0]._col_name == "id")
            for row in table.data
        ]
    )


def test_loading_from_json_with_mixed_types():
    """Test loading a Table from json instantiates the correct types.

    When a Table was saved with `allow_mixed_types=True`, the correct datatype was saved
    to the serialized json object. However, loading that Table caused an error; that
    datatype was never used in Table instantiation. This unit test makes sure this path
    runs correctly.
    """
    json_obj = {
        "_type": "table",
        "column_types": {
            "params": {
                "type_map": {
                    "Column_1": {
                        "params": {
                            "allowed_types": [
                                {"wb_type": "any"},
                                {"wb_type": "none"},
                            ]
                        },
                        "wb_type": "union",
                    },
                    "Column_2": {
                        "params": {
                            "allowed_types": [
                                {"wb_type": "any"},
                                {"wb_type": "none"},
                            ]
                        },
                        "wb_type": "union",
                    },
                }
            },
            "wb_type": "typedDict",
        },
        "columns": ["Column_1", "Column_2"],
        "data": [[0.0, None], [0.0, 5], [None, "cpu"]],
        "ncols": 2,
        "nrows": 3,
    }

    artifact = wandb.Artifact("my_artifact", type="dataset")
    _ = wandb.Table.from_json(json_obj, artifact)


def test_datetime_conversion():
    art = wandb.Artifact("A", "B")
    t = wandb.Table(
        columns=["dt", "t", "np", "d"],
        data=[
            [
                datetime.datetime(2000, 12, d),
                datetime.date(2000, 12, d),
                np.datetime64("2000-12-" + ("0" if d < 10 else "") + str(d)),
                d,
            ]
            for d in range(1, 3)
        ],
    )
    json = t.to_json(art)
    assert json["data"] == [
        [975628800000, 975628800000, 975628800000, 1],
        [975715200000, 975715200000, 975715200000, 2],
    ]


def test_table_logging_mode_validation():
    """Test that invalid logging modes raise an error."""
    with pytest.raises(AssertionError):
        wandb.Table(log_mode="INVALID_MODE")


def _logged_tables(parse_records, record_q):
    parsed = parse_records(record_q)
    history = parsed.history or parsed.partial_history
    return [json.loads(item["table"]) for item in history if "table" in item]


def _assert_logged_table(logged_table, **expected):
    assert {key: logged_table[key] for key in expected} == expected


def _logged_artifact_table_data(log_artifact, call_index):
    artifact = log_artifact.call_args_list[call_index].args[0]
    [entry] = artifact.manifest.entries.values()
    assert entry.local_path is not None
    with open(entry.local_path, encoding="utf-8") as f:
        return json.load(f)["data"]


def test_table_logging_mode_immutable_logs_table_artifact_once(
    mocker, mock_run, mock_wandb_log, parse_records, record_q
):
    """Test that mutating a logged IMMUTABLE table does not log a new artifact."""
    run = mock_run()
    log_artifact = mocker.patch.object(run, "log_artifact")
    t = wandb.Table(columns=["a"], data=[[1]], log_mode="IMMUTABLE")

    run.log({"table": t})
    t.add_data(2)
    run.log({"table": t})

    mock_wandb_log.assert_warned(
        "You are mutating a Table with log_mode='IMMUTABLE' that has been "
        "logged already. Subsequent log() calls will have no effect. "
        "Set log_mode='MUTABLE' to enable re-logging after mutations"
    )

    logged_tables = _logged_tables(parse_records, record_q)
    assert len(logged_tables) == 2
    _assert_logged_table(
        logged_tables[0],
        _type="table-file",
        log_mode="IMMUTABLE",
        nrows=1,
    )
    _assert_logged_table(
        logged_tables[1],
        _type="table-file",
        log_mode="IMMUTABLE",
    )
    assert logged_tables[1]["path"] == logged_tables[0]["path"]
    assert log_artifact.call_count == 1


def test_table_logging_mode_mutable_relogs_after_mutation(
    mocker, mock_run, parse_records, record_q
):
    """Test that MUTABLE mode allows re-logging after mutations."""
    run = mock_run()
    log_artifact = mocker.patch.object(run, "log_artifact")
    t = wandb.Table(columns=["a"], data=[[1]], log_mode="MUTABLE")

    run.log({"table": t})
    t.add_data(2)
    run.log({"table": t})

    logged_tables = _logged_tables(parse_records, record_q)
    assert len(logged_tables) == 2
    _assert_logged_table(
        logged_tables[0],
        _type="table-file",
        log_mode="MUTABLE",
        nrows=1,
    )
    _assert_logged_table(
        logged_tables[1],
        _type="table-file",
        log_mode="MUTABLE",
        nrows=2,  # Second table has 2 rows
    )
    assert logged_tables[1]["path"] != logged_tables[0]["path"]
    assert _logged_artifact_table_data(log_artifact, 0) == [[1]]
    assert _logged_artifact_table_data(log_artifact, 1) == [[1], [2]]
    assert log_artifact.call_count == 2


def test_table_logging_mode_incremental_relogs_after_mutation(
    mocker, mock_run, parse_records, record_q
):
    """Test that INCREMENTAL mode handles partial logging correctly."""
    run = mock_run()
    log_artifact = mocker.patch.object(run, "log_artifact")
    t = wandb.Table(columns=["a"], data=[[1]], log_mode="INCREMENTAL")

    run.log({"table": t})
    t.add_data(2)
    run.log({"table": t})

    logged_tables = _logged_tables(parse_records, record_q)
    assert len(logged_tables) == 2
    _assert_logged_table(
        logged_tables[0],
        _type="incremental-table-file",
        log_mode="INCREMENTAL",
        increment_num=0,
        nrows=1,
    )
    _assert_logged_table(
        logged_tables[1],
        _type="incremental-table-file",
        log_mode="INCREMENTAL",
        increment_num=1,
        nrows=2,
    )
    assert logged_tables[1]["path"] != logged_tables[0]["path"]
    assert _logged_artifact_table_data(log_artifact, 0) == [[1]]
    assert _logged_artifact_table_data(log_artifact, 1) == [[2]]
    assert log_artifact.call_count == 2


def test_table_logging_mode_incremental_operations():
    """Test that INCREMENTAL mode correctly handles unsupported operations."""
    t = wandb.Table(columns=["a", "b"], log_mode="INCREMENTAL")

    with pytest.raises(wandb.Error) as e:
        t.add_column("c", [1, 2])

    assert (
        "Operation 'add_column' is not supported for tables with"
        " log_mode='INCREMENTAL'. Use a different log mode like 'MUTABLE' or 'IMMUTABLE'."
    ) in str(e)

    def compute_fn(ndx, row):
        return {"c": row["a"] + 1}

    with pytest.raises(wandb.Error) as e:
        t.add_computed_columns(compute_fn)

    assert (
        "Operation 'add_computed_columns' is not supported for tables with"
        " log_mode='INCREMENTAL'. Use a different log mode like 'MUTABLE' or 'IMMUTABLE'."
    ) in str(e)


def test_table_logging_mode_incremental_warns_after_100_increments(
    mocker, mock_run, mock_wandb_log
):
    """Test that INCREMENTAL mode warns when exceeding 100 increments."""
    run = mock_run()
    mocker.patch.object(run, "log_artifact")
    t = wandb.Table(columns=["a"], data=[[0]], log_mode="INCREMENTAL")

    run.log({"table": t})
    for i in range(1, 101):
        t.add_data(i)
        if i < 100:
            run.log({"table": t})

    mock_wandb_log.assert_warned(
        "You have exceeded 100 increments for this table. "
        "Only the latest 100 increments will be visualized in the run workspace."
    )
