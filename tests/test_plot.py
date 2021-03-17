import pytest
from sklearn.naive_bayes import MultinomialNB
from wandb.plot import confusion_matrix, pr_curve, roc_curve


@pytest.fixture
def dummy_classifier(request):
    nb = MultinomialNB()
    x_train = [
        [1, 2],
        [1, 2],
        [1, 2],
        [1, 2],
        [2, 3],
        [3, 4],
        [3, 4],
        [3, 4],
        [3, 4],
        [3, 4],
        [3, 4],
    ]
    y_train = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
    nb.fit(x_train, y_train)
    x_test = [[4, 5], [5, 6]]
    y_test = [0, 1]
    y_probas = nb.predict_proba(x_test)
    y_pred = nb.predict(x_test)
    return (nb, x_train, y_train, x_test, y_test, y_pred, y_probas)


def test_roc(dummy_classifier, wandb_init_run):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    custom_chart_no_title = roc_curve(y_test, y_probas)
    assert custom_chart_no_title.string_fields["title"] == "ROC"
    assert custom_chart_no_title.table.data[0] == [
        0,
        0.0,
        0.0,
    ], custom_chart_no_title.table.data[0]
    custom_chart_with_title = roc_curve(y_test, y_probas, title="New title")
    assert custom_chart_with_title.string_fields["title"] == "New title"


def test_pr(dummy_classifier, wandb_init_run):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    custom_chart_no_title = pr_curve(y_test, y_probas)
    assert custom_chart_no_title.string_fields["title"] == "Precision v. Recall"
    assert custom_chart_no_title.table.data[0] == [
        0,
        1.0,
        1.0,
    ], custom_chart_no_title.table.data[0]
    custom_chart_with_title = pr_curve(y_test, y_probas, title="New title")
    assert custom_chart_with_title.string_fields["title"] == "New title"


def test_conf_mat(dummy_classifier, wandb_init_run):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    conf_mat_using_probs = confusion_matrix(probs=y_probas, y_true=y_test)
    conf_mat_using_preds = confusion_matrix(
        preds=y_pred, y_true=y_test, title="New title"
    )
    assert conf_mat_using_probs.table.data[0] == ["Class_1", "Class_1", 0.0]
    assert conf_mat_using_probs.table.data[0] == conf_mat_using_preds.table.data[0]
    assert conf_mat_using_preds.string_fields["title"] == "New title"


def test_conf_mat_missing_values_with_classes(wandb_init_run):
    class_names = ["Cat", "Dog", "Bird"]
    y_true = [1, 2, 1, 2]
    y_pred = [2, 1, 1, 2]
    conf_mat = confusion_matrix(
        preds=y_pred, y_true=y_true, class_names=class_names, title="New title"
    )
    assert conf_mat.table.data[0] == ["Cat", "Cat", 0]
    assert conf_mat.table.data[1] == ["Cat", "Dog", 0]
    assert conf_mat.table.data[2] == ["Cat", "Bird", 0]

    assert conf_mat.table.data[3] == ["Dog", "Cat", 0]
    assert conf_mat.table.data[4] == ["Dog", "Dog", 1]
    assert conf_mat.table.data[5] == ["Dog", "Bird", 1]

    assert conf_mat.table.data[6] == ["Bird", "Cat", 0]
    assert conf_mat.table.data[7] == ["Bird", "Dog", 1]
    assert conf_mat.table.data[8] == ["Bird", "Bird", 1]


def test_conf_mat_missing_values_without_classes(wandb_init_run):
    y_true = [2, 4, 2, 4, 4]
    y_pred = [4, 2, 2, 4, 6]
    conf_mat = confusion_matrix(preds=y_pred, y_true=y_true)
    assert conf_mat.table.data[0] == ["Class_1", "Class_1", 1]
    assert conf_mat.table.data[1] == ["Class_1", "Class_2", 1]
    assert conf_mat.table.data[2] == ["Class_1", "Class_3", 0]

    assert conf_mat.table.data[3] == ["Class_2", "Class_1", 1]
    assert conf_mat.table.data[4] == ["Class_2", "Class_2", 1]
    assert conf_mat.table.data[5] == ["Class_2", "Class_3", 1]

    assert conf_mat.table.data[6] == ["Class_3", "Class_1", 0]
    assert conf_mat.table.data[7] == ["Class_3", "Class_2", 0]
    assert conf_mat.table.data[8] == ["Class_3", "Class_3", 0]
