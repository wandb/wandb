import pytest

pytest.importorskip("sklearn")

from wandb.integration.sklearn import calculate


def _counts(chart):
    assert chart.table.columns == ["Predicted", "Actual", "Count"]
    return {(pred, true): count for pred, true, count in chart.table.data}


def test_confusion_matrix_rows_are_actual_and_columns_are_predicted():
    # Three samples of class 0 are predicted as class 1.
    y_true = [0, 0, 0, 1]
    y_pred = [1, 1, 1, 1]

    chart = calculate.confusion_matrix(y_true, y_pred)

    assert _counts(chart) == {(0, 0): 0, (1, 0): 3, (0, 1): 0, (1, 1): 1}


def test_confusion_matrix_with_named_labels():
    y_true = [0, 0, 0, 1]
    y_pred = [1, 1, 1, 1]

    chart = calculate.confusion_matrix(y_true, y_pred, labels=["cat", "dog"])

    assert _counts(chart) == {
        ("cat", "cat"): 0,
        ("dog", "cat"): 3,
        ("cat", "dog"): 0,
        ("dog", "dog"): 1,
    }
