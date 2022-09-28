import numpy as np
import pytest
import wandb
from wandb.sdk.integration_utils.data_logging import (
    CAN_INFER_IMAGE_AND_VIDEO,
    ValidationDataLogger,
)


def test_data_logger_val_data_lists(wandb_init):
    run = wandb_init()
    print(run.settings)
    vd = ValidationDataLogger(
        inputs=np.array([[i, i, i] for i in range(10)]),
        targets=np.array([[i] for i in range(10)]),
        indexes=None,
        validation_row_processor=None,
        prediction_row_processor=None,
        class_labels=None,
        infer_missing_processors=False,
    )

    cols = ["input", "target"]
    tcols = vd.validation_indexes[0]._table.columns
    assert set(tcols) == set(cols)
    assert np.all(
        [
            vd.validation_indexes[0]._table.data[i][tcols.index("input")].tolist()
            == [i, i, i]
            and vd.validation_indexes[0]._table.data[i][tcols.index("target")].tolist()
            == [i]
            for i in range(10)
        ]
    )
    assert vd.validation_indexes[0]._table._get_artifact_entry_ref_url() is not None
    run.finish()


def test_data_logger_val_data_dicts(wandb_init):
    run = wandb_init()
    vd = ValidationDataLogger(
        inputs={
            "ia": np.array([[i, i, i] for i in range(10)]),
            "ib": np.array([[i, i, i] for i in range(10)]),
        },
        targets={
            "ta": np.array([[i] for i in range(10)]),
            "tb": np.array([[i] for i in range(10)]),
        },
        indexes=None,
        validation_row_processor=None,
        prediction_row_processor=None,
        class_labels=None,
        infer_missing_processors=False,
    )

    cols = ["ia", "ib", "ta", "tb"]
    tcols = vd.validation_indexes[0]._table.columns
    assert set(tcols) == set(cols)
    assert np.all(
        [
            vd.validation_indexes[0]._table.data[i][tcols.index("ia")].tolist()
            == [i, i, i]
            and vd.validation_indexes[0]._table.data[i][tcols.index("ib")].tolist()
            == [i, i, i]
            and vd.validation_indexes[0]._table.data[i][tcols.index("ta")].tolist()
            == [i]
            and vd.validation_indexes[0]._table.data[i][tcols.index("tb")].tolist()
            == [i]
            for i in range(10)
        ]
    )
    assert vd.validation_indexes[0]._table._get_artifact_entry_ref_url() is not None
    run.finish()


def test_data_logger_val_indexes(wandb_init):
    run = wandb_init()
    table = wandb.Table(columns=["label"], data=[["cat"]])
    _ = ValidationDataLogger(
        inputs={
            "ia": np.array([[i, i, i] for i in range(10)]),
            "ib": np.array([[i, i, i] for i in range(10)]),
        },
        targets=None,
        indexes=[table.index_ref(0) for i in range(10)],
        validation_row_processor=None,
        prediction_row_processor=None,
        class_labels=None,
        infer_missing_processors=False,
    )
    run.finish()


def test_data_logger_val_invalid(wandb_init):
    run = wandb_init()
    with pytest.raises(AssertionError):
        _ = ValidationDataLogger(
            inputs={
                "ia": np.array([[i, i, i] for i in range(10)]),
                "ib": np.array([[i, i, i] for i in range(10)]),
            },
            targets=None,
            indexes=None,
            validation_row_processor=None,
            prediction_row_processor=None,
            class_labels=None,
            infer_missing_processors=False,
        )
    run.finish()


def test_data_logger_val_user_proc(wandb_init):
    run = wandb_init()
    vd = ValidationDataLogger(
        inputs=np.array([[i, i, i] for i in range(10)]),
        targets=np.array([[i] for i in range(10)]),
        indexes=None,
        validation_row_processor=lambda ndx, row: {
            "ip_1": row["input"] + 1,
            "tp_1": row["target"] + 1,
        },
        prediction_row_processor=None,
        class_labels=None,
        infer_missing_processors=False,
    )

    cols = [
        "input",
        "target",
        "ip_1",
        "tp_1",
    ]
    tcols = vd.validation_indexes[0]._table.columns
    assert set(tcols) == set(cols)
    assert np.all(
        [
            vd.validation_indexes[0]._table.data[i][tcols.index("input")].tolist()
            == [i, i, i]
            and vd.validation_indexes[0]._table.data[i][tcols.index("target")].tolist()
            == [i]
            and vd.validation_indexes[0]._table.data[i][tcols.index("ip_1")].tolist()
            == [i + 1, i + 1, i + 1]
            and vd.validation_indexes[0]._table.data[i][tcols.index("tp_1")].tolist()
            == [i + 1]
            for i in range(10)
        ]
    )
    assert vd.validation_indexes[0]._table._get_artifact_entry_ref_url() is not None
    run.finish()


def test_data_logger_val_inferred_proc(wandb_init):
    run = wandb_init()
    np.random.seed(42)
    vd = ValidationDataLogger(
        inputs=np.array([[i, i, i] for i in range(10)]),
        targets={
            "simple": np.random.randint(5, size=(10)),
            "wrapped": np.random.randint(5, size=(10, 1)),
            "logits": np.random.randint(5, size=(10, 5))
            + 2,  # +2 avoids only having 0s and 1s
            "nodes": np.random.randint(5, size=(10, 10)),
            "2dimages": np.random.randint(255, size=(10, 5, 5)),
            "3dimages": np.random.randint(255, size=(10, 5, 5, 3)),
            "video": np.random.randint(255, size=(10, 5, 5, 3, 10)),
        },
        indexes=None,
        validation_row_processor=None,
        prediction_row_processor=None,
        class_labels=["a", "b", "c", "d", "e"],
        infer_missing_processors=True,
    )

    cols = [
        "input",
        "simple",
        "wrapped",
        "logits",
        "nodes",
        "2dimages",
        "3dimages",
        "video",
        "input:node",
        "input:argmax",
        "input:argmin",
        "wrapped:class",
        "logits:max_class",
        "logits:score",
        "nodes:node",
        "nodes:argmax",
        "nodes:argmin",
    ]

    if CAN_INFER_IMAGE_AND_VIDEO:
        cols.append("2dimages:image")
        cols.append("3dimages:image")
        cols.append("video:video")

    tcols = vd.validation_indexes[0]._table.columns
    row = vd.validation_indexes[0]._table.data[0]

    assert set(tcols) == set(cols)
    assert np.all(row[tcols.index("input")] == [0, 0, 0])
    assert isinstance(row[tcols.index("simple")].tolist(), int)
    assert len(row[tcols.index("wrapped")]) == 1
    assert len(row[tcols.index("logits")]) == 5
    assert len(row[tcols.index("nodes")]) == 10
    assert row[tcols.index("2dimages")].shape == (5, 5)
    assert row[tcols.index("3dimages")].shape == (5, 5, 3)
    assert row[tcols.index("video")].shape == (5, 5, 3, 10)
    # assert isinstance(row[tcols.index("input:node")], dict)
    assert isinstance(row[tcols.index("input:node")], list)
    assert isinstance(row[tcols.index("input:argmax")].tolist(), int)
    assert isinstance(row[tcols.index("input:argmin")].tolist(), int)
    assert isinstance(row[tcols.index("wrapped:class")], wandb.data_types._TableIndex)
    assert isinstance(
        row[tcols.index("logits:max_class")], wandb.data_types._TableIndex
    )
    assert isinstance(row[tcols.index("logits:score")], dict)
    # assert isinstance(row[tcols.index("nodes:node")], dict)
    assert isinstance(row[tcols.index("nodes:node")], list)
    assert isinstance(row[tcols.index("nodes:argmax")].tolist(), int)
    assert isinstance(row[tcols.index("nodes:argmin")].tolist(), int)

    if CAN_INFER_IMAGE_AND_VIDEO:
        assert isinstance(row[tcols.index("2dimages:image")], wandb.data_types.Image)
        assert isinstance(row[tcols.index("3dimages:image")], wandb.data_types.Image)
        assert isinstance(row[tcols.index("video:video")], wandb.data_types.Video)
    run.finish()


def test_data_logger_val_inferred_proc_no_class(wandb_init):
    run = wandb_init()
    vd = ValidationDataLogger(
        inputs=np.array([[i, i, i] for i in range(10)]),
        targets={
            "simple": np.random.randint(5, size=(10)),
            "wrapped": np.random.randint(5, size=(10, 1)),
            "logits": np.random.randint(5, size=(10, 5))
            + 2,  # +2 avoids only having 0s and 1s
            "nodes": np.random.randint(5, size=(10, 10)),
            "2dimages": np.random.randint(255, size=(10, 5, 5)),
            "3dimages": np.random.randint(255, size=(10, 5, 5, 3)),
            "video": np.random.randint(255, size=(10, 5, 5, 3, 10)),
        },
        indexes=None,
        validation_row_processor=None,
        prediction_row_processor=None,
        class_labels=None,
        infer_missing_processors=True,
    )

    cols = [
        "input",
        "simple",
        "wrapped",
        "logits",
        "nodes",
        "2dimages",
        "3dimages",
        "video",
        "input:node",
        "input:argmax",
        "input:argmin",
        "wrapped:val",
        "logits:node",
        "logits:argmax",
        "logits:argmin",
        "nodes:node",
        "nodes:argmax",
        "nodes:argmin",
    ]

    if CAN_INFER_IMAGE_AND_VIDEO:
        cols.append("2dimages:image")
        cols.append("3dimages:image")
        cols.append("video:video")

    tcols = vd.validation_indexes[0]._table.columns

    row = vd.validation_indexes[0]._table.data[0]
    assert set(tcols) == set(cols)
    assert np.all(row[tcols.index("input")] == [0, 0, 0])
    assert isinstance(row[tcols.index("simple")].tolist(), int)
    assert len(row[tcols.index("wrapped")]) == 1
    assert len(row[tcols.index("logits")]) == 5
    assert len(row[tcols.index("nodes")]) == 10
    assert row[tcols.index("2dimages")].shape == (5, 5)
    assert row[tcols.index("3dimages")].shape == (5, 5, 3)
    assert row[tcols.index("video")].shape == (5, 5, 3, 10)
    # assert isinstance(row[tcols.index("input:node")], dict)
    assert isinstance(row[tcols.index("input:node")], list)
    assert isinstance(row[tcols.index("input:argmax")].tolist(), int)
    assert isinstance(row[tcols.index("input:argmin")].tolist(), int)
    assert isinstance(row[tcols.index("wrapped:val")].tolist(), int)
    # assert isinstance(row[tcols.index("logits:node")], dict)
    assert isinstance(row[tcols.index("logits:node")], list)
    assert isinstance(row[tcols.index("logits:argmax")].tolist(), int)
    assert isinstance(row[tcols.index("logits:argmin")].tolist(), int)
    # assert isinstance(row[tcols.index("nodes:node")], dict)
    assert isinstance(row[tcols.index("nodes:node")], list)
    assert isinstance(row[tcols.index("nodes:argmax")].tolist(), int)
    assert isinstance(row[tcols.index("nodes:argmin")].tolist(), int)

    if CAN_INFER_IMAGE_AND_VIDEO:
        assert isinstance(row[tcols.index("2dimages:image")], wandb.data_types.Image)
        assert isinstance(row[tcols.index("3dimages:image")], wandb.data_types.Image)
        assert isinstance(row[tcols.index("video:video")], wandb.data_types.Video)
    run.finish()


def test_data_logger_pred(wandb_init):
    run = wandb_init()
    vd = ValidationDataLogger(
        inputs=np.array([[i, i, i] for i in range(10)]),
        targets=np.array([[i] for i in range(10)]),
        indexes=None,
        validation_row_processor=None,
        prediction_row_processor=None,
        class_labels=None,
        infer_missing_processors=False,
    )
    t = vd.log_predictions(vd.make_predictions(lambda inputs: inputs[:, 0]))
    cols = ["val_row", "output"]
    tcols = t.columns

    assert set(tcols) == set(cols)
    assert np.all([t.data[i] == [i, i] for i in range(10)])
    assert t._get_artifact_entry_ref_url() is not None
    run.finish()


def test_data_logger_pred_user_proc(wandb_init):
    run = wandb_init()
    vd = ValidationDataLogger(
        inputs=np.array([[i, i, i] for i in range(10)]),
        targets=np.array([[i] for i in range(10)]),
        indexes=None,
        validation_row_processor=None,
        prediction_row_processor=lambda ndx, row: {"oa": row["output"] + 1},
        class_labels=None,
        infer_missing_processors=False,
    )
    t = vd.log_predictions(vd.make_predictions(lambda inputs: inputs[:, 0]))
    cols = ["val_row", "output", "oa"]
    tcols = t.columns

    assert set(tcols) == set(cols)
    assert np.all([t.data[i] == [i, i, i + 1] for i in range(10)])
    assert t._get_artifact_entry_ref_url() is not None
    run.finish()


def test_data_logger_pred_inferred_proc(wandb_init):
    run = wandb_init()
    vd = ValidationDataLogger(
        inputs=np.array([[i, i, i] for i in range(10)]),
        targets=np.array([[i] for i in range(10)]),
        indexes=None,
        validation_row_processor=None,
        prediction_row_processor=None,
        class_labels=["a", "b", "c", "d", "e"],
        infer_missing_processors=True,
    )
    t = vd.log_predictions(
        vd.make_predictions(
            lambda inputs: {
                "simple": np.random.randint(5, size=(10)),
                "wrapped": np.random.randint(5, size=(10, 1)),
                "logits": np.random.randint(5, size=(10, 5))
                + 2,  # +2 avoids only having 0s and 1s
                "nodes": np.random.randint(5, size=(10, 10)),
                "2dimages": np.random.randint(255, size=(10, 5, 5)),
                "3dimages": np.random.randint(255, size=(10, 5, 5, 3)),
                "video": np.random.randint(255, size=(10, 5, 5, 3, 10)),
            }
        )
    )

    cols = [
        "val_row",
        "simple",
        "wrapped",
        "logits",
        "nodes",
        "2dimages",
        "3dimages",
        "video",
        "wrapped:class",
        "logits:max_class",
        "logits:score",
        "nodes:node",
        "nodes:argmax",
        "nodes:argmin",
    ]

    if CAN_INFER_IMAGE_AND_VIDEO:
        cols.append("2dimages:image")
        cols.append("3dimages:image")
        cols.append("video:video")

    tcols = t.columns
    row = t.data[0]

    assert set(tcols) == set(cols)
    assert isinstance(row[tcols.index("val_row")], wandb.data_types._TableIndex)
    assert isinstance(row[tcols.index("simple")].tolist(), int)
    assert len(row[tcols.index("wrapped")]) == 1
    assert len(row[tcols.index("logits")]) == 5
    assert len(row[tcols.index("nodes")]) == 10
    assert row[tcols.index("2dimages")].shape == (5, 5)
    assert row[tcols.index("3dimages")].shape == (5, 5, 3)
    assert row[tcols.index("video")].shape == (5, 5, 3, 10)
    assert isinstance(row[tcols.index("wrapped:class")], wandb.data_types._TableIndex)
    assert isinstance(
        row[tcols.index("logits:max_class")], wandb.data_types._TableIndex
    )
    assert isinstance(row[tcols.index("logits:score")], dict)
    # assert isinstance(row[tcols.index("nodes:node")], dict)
    assert isinstance(row[tcols.index("nodes:node")], list)
    assert isinstance(row[tcols.index("nodes:argmax")].tolist(), int)
    assert isinstance(row[tcols.index("nodes:argmin")].tolist(), int)

    if CAN_INFER_IMAGE_AND_VIDEO:
        assert isinstance(row[tcols.index("2dimages:image")], wandb.data_types.Image)
        assert isinstance(row[tcols.index("3dimages:image")], wandb.data_types.Image)
        assert isinstance(row[tcols.index("video:video")], wandb.data_types.Video)
    run.finish()


def test_data_logger_pred_inferred_proc_no_classes(wandb_init):
    run = wandb_init()
    vd = ValidationDataLogger(
        inputs=np.array([[i, i, i] for i in range(10)]),
        targets=np.array([[i] for i in range(10)]),
        indexes=None,
        validation_row_processor=None,
        prediction_row_processor=None,
        class_labels=None,
        infer_missing_processors=True,
    )

    t = vd.log_predictions(
        vd.make_predictions(
            lambda inputs: {
                "simple": np.random.randint(5, size=(10)),
                "wrapped": np.random.randint(5, size=(10, 1)),
                "logits": np.random.randint(5, size=(10, 5))
                + 2,  # +2 avoids only having 0s and 1s
                "nodes": np.random.randint(5, size=(10, 10)),
                "2dimages": np.random.randint(255, size=(10, 5, 5)),
                "3dimages": np.random.randint(255, size=(10, 5, 5, 3)),
                "video": np.random.randint(255, size=(10, 5, 5, 3, 10)),
            }
        )
    )

    cols = [
        "val_row",
        "simple",
        "wrapped",
        "logits",
        "nodes",
        "2dimages",
        "3dimages",
        "video",
        "wrapped:val",
        "logits:node",
        "logits:argmax",
        "logits:argmin",
        "nodes:node",
        "nodes:argmax",
        "nodes:argmin",
    ]
    if CAN_INFER_IMAGE_AND_VIDEO:
        cols.append("2dimages:image")
        cols.append("3dimages:image")
        cols.append("video:video")

    tcols = t.columns

    row = t.data[0]

    assert set(tcols) == set(cols)
    assert isinstance(row[tcols.index("val_row")], wandb.data_types._TableIndex)
    assert isinstance(row[tcols.index("simple")].tolist(), int)
    assert len(row[tcols.index("wrapped")]) == 1
    assert len(row[tcols.index("logits")]) == 5
    assert len(row[tcols.index("nodes")]) == 10
    assert row[tcols.index("2dimages")].shape == (5, 5)
    assert row[tcols.index("3dimages")].shape == (5, 5, 3)
    assert row[tcols.index("video")].shape == (5, 5, 3, 10)
    assert isinstance(row[tcols.index("wrapped:val")].tolist(), int)
    # assert isinstance(row[tcols.index("logits:node")], dict)
    assert isinstance(row[tcols.index("logits:node")], list)
    assert isinstance(row[tcols.index("logits:argmax")].tolist(), int)
    assert isinstance(row[tcols.index("logits:argmin")].tolist(), int)
    # assert isinstance(row[tcols.index("nodes:node")], dict)
    assert isinstance(row[tcols.index("nodes:node")], list)
    assert isinstance(row[tcols.index("nodes:argmax")].tolist(), int)
    assert isinstance(row[tcols.index("nodes:argmin")].tolist(), int)

    if CAN_INFER_IMAGE_AND_VIDEO:
        assert isinstance(row[tcols.index("2dimages:image")], wandb.data_types.Image)
        assert isinstance(row[tcols.index("3dimages:image")], wandb.data_types.Image)
        assert isinstance(row[tcols.index("video:video")], wandb.data_types.Video)
    run.finish()
