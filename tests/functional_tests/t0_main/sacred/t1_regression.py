from numpy.random import permutation
from sacred import Experiment
from sklearn import datasets, svm
from wandb.sacred import WandbObserver

ex = Experiment("iris_rbf_svm")
ex.observers.append(WandbObserver(project="sacred_test", name="test1"))


@ex.config
def cfg():
    c = 1.0  # noqa: F841
    gamma = 0.7  # noqa: F841


@ex.automain
def run(c, gamma):
    iris = datasets.load_iris()
    per = permutation(iris.target.size)
    iris.data = iris.data[per]
    iris.target = iris.target[per]
    clf = svm.SVC(C=c, kernel="rbf", gamma=gamma)
    clf.fit(iris.data[:90], iris.target[:90])
    return clf.score(iris.data[90:], iris.target[90:])
