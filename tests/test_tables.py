import wandb
import pytest


def test_pk_cast(use_helper=False):
    # Base Case
    table = wandb.Table(columns=["id", "b"], data=[["1", "a"], ["2", "b"]])

    # Validate that iterrows works as intended for no pks
    assert [id_ for id_, row in list(table.iterrows())] == [0, 1]

    # Cast as a PK
    if use_helper:
        table.set_pk("id")
    else:
        table.cast("id", wandb.data_types._TablePrimaryKeyType())
    # import pdb; pdb.set_trace()
    # Now iterrows has the pk as the id field
    assert [id_ for id_, row in list(table.iterrows())] == ["1", "2"]

    # Adding is supported
    table.add_data("3", "c")

    # Adding Duplicates fail
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
        wandb.data_types._TablePrimaryKeyType,
    )

    # Assert that multiple PKs are not supported
    with pytest.raises(AssertionError):
        if use_helper:
            table.set_pk("b")
        else:
            table.cast("b", wandb.data_types._TablePrimaryKeyType())

    # Fails on Numerics for now
    table = wandb.Table(columns=["id", "b"], data=[[1, "a"], [2, "b"]])
    with pytest.raises(TypeError):
        if use_helper:
            table.set_pk("id")
        else:
            table.cast("id", wandb.data_types._TablePrimaryKeyType())

    # Assert that the table was not modified
    assert all([row[0].__class__ == int for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["id"],
        wandb.data_types._TablePrimaryKeyType,
    )

    # Fails on initial duplicates
    # table = wandb.Table(columns=["id", "b"], data=[["1", "a"], ["1", "b"]])
    # with pytest.raises(TypeError):
    #     if use_helper:
    #         table.set_pk("id")
    #     else:
    #         table.cast("id", wandb.data_types._TablePrimaryKeyType())

    # # Assert that the table was not modified
    # assert all([row[0].__class__ == str for row in table.data])
    # assert not isinstance(
    #     table._column_types.params["type_map"]["id"],wandb.data_types._TableForeignKeyType
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
        table.cast("fk", wandb.data_types._TableForeignKeyType(table_a, "id"))

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
        wandb.data_types._TableForeignKeyType,
    )

    # Fails on Numerics for now
    table = wandb.Table(columns=["fk", "col_2"], data=[[1, "c"], [2, "d"]])
    with pytest.raises(TypeError):
        if use_helper:
            table.set_fk("fk", table_a, "id")
        else:
            table.cast("fk", wandb.data_types._TableForeignKeyType(table_a, "id"))

    # Assert that the table was not modified
    assert all([row[0].__class__ == int for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["fk"],
        wandb.data_types._TableForeignKeyType,
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

    # None should be supported in the case that the FK was originally optional
    table.add_data(None, "c")

    # import pdb; pdb.set_trace()

    # Assert that the data in this column is valid, but also properly typed
    # import pdb; pdb.set_trace()
    assert [row[0] for row in table.data] == ["1", "2", "3", None]
    assert all(
        [
            row[0] is None or (row[0]._table == table_a and row[0]._col_name == "id")
            for row in table.data
        ]
    )

    table = wandb.Table(columns=["fk", "col_2"], data=[["1", "c"], ["2", "d"]])
    table.add_data(table_a.data[0][0], "c")
    table.add_data(None, "c")

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == ["1", "2", "1", None]
    assert all(
        [
            row[0] is None or (row[0]._table == table_a and row[0]._col_name == "id")
            for row in table.data
        ]
    )


def test_fk_from_pk_local_logged():
    raise NotImplementedError


def test_fk_from_pk_public():
    raise NotImplementedError


def test_default_pk():
    raise NotImplementedError


def test_deserialization():
    raise NotImplementedError
