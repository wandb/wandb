import pytest


def test_import_order():
    # monkeypatching tf.keras caused import issue
    _ = pytest.importorskip("wandb.keras.WandbCallback", reason="imports tensorflow")

    tf = pytest.importorskip(
        "tensorflow", minversion="2.6.2", reason="only relevant for tf>=2.6"
    )
    keras = pytest.importorskip(
        "keras", minversion="2.6", reason="only relevant for keras>=2.6"
    )

    assert isinstance(tf.keras.Model(), keras.Model)
