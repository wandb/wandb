import pytest
from sklearn.naive_bayes import MultinomialNB
import wandb
from wandb.sklearn import learning_curve, roc

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

def test_learning_curve(dummy_classifier):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    lc_table = learning_curve(nb, x_train, y_train)
    assert(len(lc_table.data) == 10)
    assert(lc_table.data[0][0] == 'train')
    assert(lc_table.data[1][0] == 'test')

def test_roc(dummy_classifier):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    lc_table = learning_curve(nb, x_train, y_train)
    r = roc(y_test, y_probas)
    
    assert(r.data[0] == [0, 0.0, 1.0])
