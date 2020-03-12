import pytest
from sklearn.naive_bayes import MultinomialNB
import wandb
from wandb.plots.roc import roc
from wandb.sklearn import learning_curve
from wandb.plots.precision_recall import precision_recall
from wandb.plots.heatmap import heatmap

@pytest.fixture
def dummy_classifier(request):
    nb = MultinomialNB()
    x_train = [[1,2],[1,2],[1,2],[1,2],[2,3],[3,4],[3,4],[3,4],[3,4],[3,4],[3,4]]
    y_train = [0,0,0,0,0,1,1,1,1,1,1]
    nb.fit(x_train, y_train)
    x_test = [[4,5], [5,6]]
    y_test = [0,1]
    y_probas = nb.predict_proba(x_test)
    y_pred = nb.predict(x_test)
    return (nb, x_train, y_train, x_test, y_test, y_pred, y_probas)

def test_roc(dummy_classifier):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    lc_table = learning_curve(nb, x_train, y_train)
    r = roc(y_test, y_probas)

    assert(r.value.data[0] == [0, 0.0, 0.0])

def test_precision_recall(dummy_classifier):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    pr = precision_recall(y_test, y_probas)

    assert(pr.value.data[0]== [0, 1.0, 1.0])

def test_heatmap():
    matrix_values = [[1,2],[3,4],[5,6],[7,8],[9,10]]
    x_labels=['a', 'b']
    y_labels=['A', 'B', 'C', 'D', 'E']
    hm = heatmap(x_labels, y_labels, matrix_values)

    assert(hm.value.data[4]== ['a', 'E', 9])
