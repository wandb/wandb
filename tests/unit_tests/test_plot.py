import pytest
from wandb.plot import confusion_matrix, line_series, pr_curve, roc_curve


def test_roc_curve_no_title():
    """Test ROC curve with no title.

    The ROC curve is created with two sets of probabilities. The expected data
    is pre-defined and compared with the actual data. The title is also checked.
    """
    chart = roc_curve(
        y_true=[0, 1],
        y_probas=[
            (0.4, 0.6),
            (0.8, 0.2),
        ],
    )
    assert chart.spec.string_fields["title"] == "ROC Curve"
    assert chart.table.data == [
        [0, 0.0, 0.0],
        [0, 1.0, 0.0],
        [0, 1.0, 1.0],
        [1, 0.0, 0.0],
        [1, 1.0, 0.0],
        [1, 1.0, 1.0],
    ]


def test_roc_curve_with_title():
    """Test ROC curve with a title.

    The ROC curve is created with two sets of probabilities and a title. The
    expected data is pre-defined and compared with the actual data. The title
    is also checked.
    """
    chart = roc_curve(
        y_true=[0, 1],
        y_probas=[
            (0.4, 0.6),
            (0.3, 0.7),
        ],
        title="New title",
    )

    assert chart.spec.string_fields["title"] == "New title"
    assert chart.table.data == [
        [0, 0.0, 0.0],
        [0, 0.0, 1.0],
        [0, 1.0, 1.0],
        [1, 0.0, 0.0],
        [1, 0.0, 1.0],
        [1, 1.0, 1.0],
    ]


def test_pr_curve_no_title():
    """Test precision-recall curve with no title.

    The precision-recall curve is created with two sets of probabilities. The
    expected data is pre-defined and compared with the actual data. The title
    is also checked.
    """
    chart = pr_curve(
        y_true=[0, 1],
        y_probas=[
            (0.4, 0.6),
            (0.8, 0.2),
        ],
        interp_size=4,
    )
    assert chart.spec.string_fields["title"] == "Precision-Recall Curve"
    assert chart.table.data == [
        [0, 0.5, 1.0],
        [0, 0.5, 0.667],
        [0, 0.5, 0.333],
        [0, 1.0, 0.0],
        [1, 0.5, 1.0],
        [1, 0.5, 0.667],
        [1, 0.5, 0.333],
        [1, 1.0, 0.0],
    ]


def test_pr_curve_with_title():
    """Test precision-recall curve with a title.

    The precision-recall curve is created with two sets of probabilities and a
    title. The expected data is pre-defined and compared with the actual data.
    The title is also checked.
    """
    chart = pr_curve(
        y_true=[0, 1],
        y_probas=[
            (0.4, 0.6),
            (0.8, 0.2),
        ],
        interp_size=4,
        title="New title",
    )
    assert chart.spec.string_fields["title"] == "New title"
    assert chart.table.data == [
        [0, 0.5, 1.0],
        [0, 0.5, 0.667],
        [0, 0.5, 0.333],
        [0, 1.0, 0.0],
        [1, 0.5, 1.0],
        [1, 0.5, 0.667],
        [1, 0.5, 0.333],
        [1, 1.0, 0.0],
    ]


def test_confusion_matrix():
    """Test confusion matrix with probabilities and predictions

    The result of the confusion matrix using probabilities and predictions should
    be the same. The expected data is pre-defined and compared with the actual data.
    """
    chart_w_probs = confusion_matrix(
        y_true=[0, 1],
        probs=[
            (0.4, 0.6),
            (0.2, 0.8),
        ],
    )
    chart_w_preds = confusion_matrix(
        y_true=[0, 1],
        preds=[1, 1],
    )
    assert chart_w_probs.table.data == chart_w_preds.table.data
    assert chart_w_preds.table.data == [
        ["Class_1", "Class_1", 0],
        ["Class_1", "Class_2", 1],
        ["Class_2", "Class_1", 0],
        ["Class_2", "Class_2", 1],
    ]
    assert chart_w_probs.spec == chart_w_preds.spec
    assert chart_w_probs.spec.string_fields["title"] == "Confusion Matrix Curve"


def test_confusion_matrix_with_predictions():
    """Test confusion matrix using predictions

    The confusion matrix is created using predictions. Note that the class names
    are zero-indexed.
    """
    chart = confusion_matrix(
        y_true=[0, 2, 1, 2],
        preds=[2, 1, 1, 2],
        class_names=["Cat", "Dog", "Bird"],
        title="New title",
    )
    assert chart.spec.string_fields["title"] == "New title"
    assert chart.table.data == [
        ["Cat", "Cat", 0],
        ["Cat", "Dog", 0],
        ["Cat", "Bird", 1],
        ["Dog", "Cat", 0],
        ["Dog", "Dog", 1],
        ["Dog", "Bird", 0],
        ["Bird", "Cat", 0],
        ["Bird", "Dog", 1],
        ["Bird", "Bird", 1],
    ]


def test_confusion_matrix_without_class_names():
    """Test confusion matrix without class names

    The class names are generated automatically. The class names will only be
    for the unique values in the predictions and true labels.
    """
    chart = confusion_matrix(
        y_true=[2, 4, 2, 4, 4],
        preds=[4, 2, 2, 4, 6],
    )
    assert chart.table.data == [
        ["Class_1", "Class_1", 1],
        ["Class_1", "Class_2", 1],
        ["Class_1", "Class_3", 0],
        ["Class_2", "Class_1", 1],
        ["Class_2", "Class_2", 1],
        ["Class_2", "Class_3", 1],
        ["Class_3", "Class_1", 0],
        ["Class_3", "Class_2", 0],
        ["Class_3", "Class_3", 0],
    ]


@pytest.mark.parametrize(
    "x_values",
    [
        ["600417", "600421"],
        [613, 215],
    ],
)
@pytest.mark.parametrize(
    "y_values",
    [
        [[3, 4]],
        [["3", "4"]],
        [[1, 2], [7.1, 8.3]],
    ],
)
def test_line_series(x_values, y_values):
    """Test line series chart with different data types.

    The x_values and y_values are used to create a line series chart. The
    expected data structure is built dynamically to compare with the actual
    data structure.
    """
    chart = line_series(xs=x_values, ys=y_values)

    # Build the expected data structure dynamically
    expected_data = []
    for idx, y_values_line in enumerate(y_values):
        line_label = f"line_{idx}"
        for x, y in zip(x_values, y_values_line):
            expected_data.append([x, line_label, y])

    assert chart.table.data == expected_data


@pytest.mark.parametrize(
    ["arguments", "exception"],
    [
        [
            {"xs": 1, "ys": [[3, 4]]},
            TypeError,
        ],
        [
            {"xs": [1], "ys": [3]},
            TypeError,
        ],
        [
            {"xs": [1], "ys": 3},
            TypeError,
        ],
        [
            {"xs": [[1], [2]], "ys": [3]},
            ValueError,
        ],
        [
            {"xs": [1, 2], "ys": [[3, 4]], "keys": ["a", "b"]},
            ValueError,
        ],
    ],
)
def test_line_series_invalid_inputs(arguments, exception):
    """Test line series chart with invalid inputs."""
    with pytest.raises(exception):
        line_series(**arguments)
