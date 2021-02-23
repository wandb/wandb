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
