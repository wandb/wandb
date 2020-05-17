import pytest
from sklearn.naive_bayes import MultinomialNB
from sklearn.linear_model import ElasticNet
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.datasets import make_regression, make_hastie_10_2
from keras.layers import Dense, Flatten, Reshape
from keras.models import Sequential
from keras import backend as K
from wandb.keras import WandbCallback
import wandb
from wandb.sklearn import learning_curve, roc, confusion_matrix, precision_recall, plot_feature_importances

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

@pytest.fixture
def dummy_model(request):
    K.clear_session()
    multi = request.node.get_closest_marker('multiclass')
    image_output = request.node.get_closest_marker('image_output')
    if multi:
        nodes = 10
        loss = 'categorical_crossentropy'
    else:
        nodes = 1
        loss = 'binary_crossentropy'
    nodes = 1 if not multi else 10
    if image_output:
        nodes = 300
    model = Sequential()
    model.add(Flatten(input_shape=(10, 10, 3)))
    model.add(Dense(nodes, activation='sigmoid'))
    if image_output:
        model.add(Dense(nodes, activation="relu"))
        model.add(Reshape((10, 10, 3)))
    model.compile(optimizer='adam',
                  loss=loss,
                  metrics=['accuracy'])
    return model

@pytest.fixture
def dummy_data(request):
    multi = request.node.get_closest_marker('multiclass')
    image_output = request.node.get_closest_marker('image_output')
    cats = 10 if multi else 1
    import numpy as np
    data = np.random.randint(255, size=(100, 10, 10, 3))
    labels = np.random.randint(2, size=(100, cats))
    if image_output:
        labels = data
    return (data, labels)

def test_learning_curve(dummy_classifier):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    lc_table = learning_curve(nb, x_train, y_train)
    assert(len(lc_table.value.data) == 10)
    assert(lc_table.value.data[0][0] == 'train')
    assert(lc_table.value.data[1][0] == 'test')

def test_roc(dummy_classifier):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    lc_table = learning_curve(nb, x_train, y_train)
    r = roc(y_test, y_probas)

    assert(r.value.data[0] == [0, 0.0, 0.0])

def test_confusion_matrix(dummy_classifier):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    cm = confusion_matrix(y_test, y_pred)
    assert(len(cm.value.data)==4)
    assert(cm.value.data[0]== [0,0,0])

def test_precision_recall(dummy_classifier):
    (nb, x_train, y_train, x_test, y_test, y_pred, y_probas) = dummy_classifier
    pr = precision_recall(y_test, y_probas)

    assert(pr.value.data[0]== [0, 1.0, 1.0])

def test_feature_importance_attribute_does_not_exists(wandb_init_run, dummy_model, dummy_data):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36,
                    callbacks=[WandbCallback()])
    dummy_features = []

    result = plot_feature_importances(dummy_model, feature_names=dummy_features)

    assert result is None

def test_feature_importance_attribute_exists_for_elasticnet(wandb_init_run):
    X, y = make_regression(n_features=2, random_state=42)
    two_features = ['a', 'b']
    model = ElasticNet(random_state=42)
    model.fit(X, y)

    result = plot_feature_importances(model, feature_names=two_features)

    assert isinstance(result, wandb.viz.Visualize)

def test_feature_importance_attribute_exists_for_random_forest(wandb_init_run):
    X, y = make_hastie_10_2(random_state=0)

    model = GradientBoostingClassifier(n_estimators=100, learning_rate=1.0, max_depth=1, random_state=42)
    ten_features = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'k']
    model.fit(X, y)

    result = plot_feature_importances(model, feature_names=ten_features)

    assert isinstance(result, wandb.viz.Visualize)