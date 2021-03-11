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
        table.cast("id", wandb.data_types._TableKeyType(table, "id"))

    # Now iterrows has the pk as the id field
    assert [id_ for id_, row in list(table.iterrows())] == ["1", "2"]

    # Adding is supported
    table.add_data("3", "c")

    # Adding Duplicates fail
    # with pytest.raises(TypeError):
    #     table.add_data("3", "d")

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == ["1", "2", "3"]
    assert all(row[0]._table == table for row in table.data)
    assert isinstance(
        table._column_types.params["type_map"]["id"], wandb.data_types._TableKeyType
    )

    # Assert that multiple PKs are not supported
    with pytest.raises(AssertionError):
        if use_helper:
            table.set_pk("b")
        else:
            table.cast("b", wandb.data_types._TableKeyType(table, "id"))

    # Fails on Numerics for now
    table = wandb.Table(columns=["id", "b"], data=[[1, "a"], [2, "b"]])
    with pytest.raises(TypeError):
        if use_helper:
            table.set_pk("id")
        else:
            table.cast("id", wandb.data_types._TableKeyType(table, "id"))

    # Assert that the table was not modified
    assert all([row[0].__class__ == int for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["id"], wandb.data_types._TableKeyType
    )

    # Fails on initial duplicates
    # table = wandb.Table(columns=["id", "b"], data=[["1", "a"], ["1", "b"]])
    # with pytest.raises(TypeError):
    #     if use_helper:
    #         table.set_pk("id")
    #     else:
    #         table.cast("id", wandb.data_types._TableKeyType(table, "id"))

    # # Assert that the table was not modified
    # assert all([row[0].__class__ == str for row in table.data])
    # assert not isinstance(
    #     table._column_types.params["type_map"]["id"],wandb.data_types._TableKeyType
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
        table.cast("fk", wandb.data_types.ForeignKey(table_a, "id"))

    # Adding is supported
    table.add_data("3", "c")

    # Adding Duplicates is supported
    with pytest.raises(TypeError):
        table.add_data("3", "d")

    # TODO: Implement constraint to only allow valid keys

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == ["1", "2", "3", "3"]
    assert all(row[0]._table == table_a for row in table.data)
    assert isinstance(
        table._column_types.params["type_map"]["id"], wandb.data_types.ForeignKey
    )

    # Fails on Numerics for now
    table = wandb.Table(columns=["fk", "col_2"], data=[["1", "c"], ["2", "d"]])
    with pytest.raises(TypeError):
        if use_helper:
            table.set_fk("fk", table_a, "id")
        else:
            table.cast("fk", wandb.data_types.ForeignKey(table_a, "id"))

    # Assert that the table was not modified
    assert all([row[0].__class__ == str for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["id"], wandb.data_types.ForeignKey
    )

    # Assert that the table was not modified
    assert all([row[0].__class__ == str for row in table.data])
    assert not isinstance(
        table._column_types.params["type_map"]["id"], wandb.data_types._TableKey
    )


def test_fk_helper():
    test_fk_cast(use_helper=True)


def test_fk_from_pk_local_draft():
    table_a = wandb.Table(columns=["id", "col_1"], data=[["1", "a"], ["2", "b"]])
    table_a.set_pk("id")

    table = wandb.Table(
        columns=["fk", "col_2"], data=[[table_a.data[0][1], "c"], ["2", "d"]]
    )
    table.add_data("3", "c")

    # Assert that the data in this column is valid, but also properly typed
    assert [row[0] for row in table.data] == ["1", "2", "3"]
    assert all(wandb.Table._table_of_key(row[0]) == table_a for row in table.data)
    assert isinstance(
        table._column_types.params["type_map"]["id"], wandb.data_types.ForeignKey
    )


def test_fk_from_pk_local_logged():
    raise NotImplementedError


def test_fk_from_pk_public():
    raise NotImplementedError


def test_default_pk():
    raise NotImplementedError


def test_deserialization():
    raise NotImplementedError
