import wandb
import pytest


def test_basic_ndx():
    # Base Case
    table_a = wandb.Table(columns=["b"], data=[["a"], ["b"]])
    table = wandb.Table(columns=["fi", "c"])
    for _ndx, row in table_a.iterrows():
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
        table.cast("id", wandb.data_types._PrimaryKeyType())

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
        table._column_types.params["type_map"]["id"], wandb.data_types._PrimaryKeyType,
    )

    # Assert that multiple PKs are not supported
    with pytest.raises(AssertionError):
        if use_helper:
            table.set_pk("b")
        else:
            table.cast("b", wandb.data_types._PrimaryKeyType())

    # Fails on Numerics for now
    table = wandb.Table(columns=["id", "b"], data=[[1, "a"], [2, "b"]])
    with pytest.raises(TypeError):
        if use_helper:
            table.set_pk("id")
        else:
            table.cast("id", wandb.data_types._PrimaryKeyType())

    # Assert that the table was not modified
    assert all([row[0].__class__ == int for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["id"], wandb.data_types._PrimaryKeyType,
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
        table.cast("fk", wandb.data_types._ForeignKeyType(table_a, "id"))

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
        table._column_types.params["type_map"]["fk"], wandb.data_types._ForeignKeyType,
    )

    # Fails on Numerics for now
    table = wandb.Table(columns=["fk", "col_2"], data=[[1, "c"], [2, "d"]])
    with pytest.raises(TypeError):
        if use_helper:
            table.set_fk("fk", table_a, "id")
        else:
            table.cast("fk", wandb.data_types._ForeignKeyType(table_a, "id"))

    # Assert that the table was not modified
    assert all([row[0].__class__ == int for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["fk"], wandb.data_types._ForeignKeyType,
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
