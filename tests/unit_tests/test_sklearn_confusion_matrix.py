import pytest
from wandb.integration.sklearn import calculate

Y_TRUE = [0, 1, 2, 2, 1]
Y_PRED = [0, 2, 2, 1, 1]


def table_rows(chart):
    return {(pred, true): count for pred, true, count in chart.table.data}


def test_confusion_matrix_rows_are_actual_columns_are_predicted():
    rows = table_rows(calculate.confusion_matrix(Y_TRUE, Y_PRED))

    assert rows[(2, 1)] == 1  # actual 1, predicted 2
    assert rows[(1, 2)] == 1  # actual 2, predicted 1
    assert rows[(1, 1)] == 1


def test_confusion_matrix_true_labels():
    rows = table_rows(calculate.confusion_matrix(Y_TRUE, Y_PRED, true_labels=[0, 1]))

    assert {true for _, true in rows} == {0, 1}
    assert {pred for pred, _ in rows} == {0, 1, 2}
    assert rows[(2, 1)] == 1


def test_confusion_matrix_pred_labels():
    rows = table_rows(calculate.confusion_matrix(Y_TRUE, Y_PRED, pred_labels=[2]))

    assert rows == {(2, 0): 0, (2, 1): 1, (2, 2): 1}


@pytest.mark.parametrize("option", ["true_labels", "pred_labels"])
def test_confusion_matrix_unknown_labels(option):
    with pytest.raises(
        ValueError, match=rf"{option} contains labels not in classes: \[5\]"
    ):
        calculate.confusion_matrix(Y_TRUE, Y_PRED, **{option: [0, 5]})


def test_confusion_matrix_display_labels_with_missing_class():
    args = dict(y_true=[0, 0, 2], y_pred=[2, 2, 2], labels=["dog", "cat", "owl"])

    rows = table_rows(calculate.confusion_matrix(**args))
    assert rows == {
        ("dog", "dog"): 0,
        ("owl", "dog"): 2,
        ("dog", "owl"): 0,
        ("owl", "owl"): 1,
    }

    rows = table_rows(calculate.confusion_matrix(**args, pred_labels=["owl"]))
    assert rows == {("owl", "dog"): 2, ("owl", "owl"): 1}
