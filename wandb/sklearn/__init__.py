import wandb
import sklearn
import numpy as np
import scikitplot
import matplotlib.pyplot as plt
from keras.callbacks import LambdaCallback
from __future__ import absolute_import, division, print_function, \
    unicode_literals
from sklearn.model_selection import learning_curve

counter = 1

def round_3(n):
    return round(n, 3)


def log(*estimators, X=None, y=None, X_test=None, y_test=None, labels=None):
    global counter

    classifier_columns = ["name", "accuracy_score", "precision", "recall", "f1_score"]
    classifier_table = wandb.Table(classifier_columns)

    regressor_columns = ["mame", "mae", "mse", "r2_score"]
    regressor_table = wandb.Table(regressor_columns)

    for estimator in estimators:
        name = estimator.__class__.__name__ + "_" + str(counter)

        def prefix(s):
            return name + "_" + s

        for v in vars(estimator):
            if isinstance(getattr(estimator, v), str) \
                or isinstance(getattr(estimator, v), bool) \
                    or isinstance(getattr(estimator, v), int) \
                    or isinstance(getattr(estimator, v), float):
                wandb.config[prefix(v)] = getattr(estimator, v)

        if sklearn.base.is_classifier(estimator):
            if X is not None and y is not None:
                fig = plt.figure()
                ax = plt.axes()
                # Learning Curve
                plot_learning_curve(estimator, X, y)

                # scores["auc"] = sklearn.metrics.auc(X, y)
            if X_test is not None and y_test is not None:
                y_pred = estimator.predict(X_test)
                y_probas = estimator.predict_proba(X_test)

                # ROC Curve
                fig = plt.figure()
                ax = plt.axes()
                scikitplot.metrics.plot_roc(y_test, y_probas, ax=ax)
                wandb.log({prefix("roc"): fig}, commit=False)

                # Confusion Matrix
                fig = plt.figure()
                ax = plt.axes()
                scikitplot.metrics.plot_confusion_matrix(y_test, y_pred, ax=ax)
                wandb.log({prefix("confusion_matrix"): fig}, commit=False)

                # Table with precision, recall, f1, accuracy and other scores
                classifier_table.add_data(
                    name,
                    round_3(sklearn.metrics.accuracy_score(y_test, y_pred)),
                    round_3(sklearn.metrics.precision_score(y_test, y_pred, average="weighted")),
                    round_3(sklearn.metrics.recall_score(y_test, y_pred, average="weighted")),
                    round_3(sklearn.metrics.f1_score(y_test, y_pred, average="weighted"))
                )

            # Feature Importances
            if labels is not None:
                fig = plt.figure()
                ax = plt.axes()
                scikitplot.estimators.plot_feature_importances(estimator, feature_names=labels, ax=ax)
                wandb.log({prefix("feature_importances"): fig}, commit=False)
        elif sklearn.base.is_regressor(estimator):
            if X is not None and y is not None:
                fig = plt.figure()
                ax = plt.axes()
                # Learning Curve
                scikitplot.estimators.plot_learning_curve(estimator, X, y, ax=ax)
                wandb.log({prefix("learning_curve"): fig}, commit=False)

            if X_test is not None and y_test is not None:
                y_pred = estimator.predict(X_test)

                # Table with MAE, MSE and R2
                mae = sklearn.metrics.mean_absolute_error(y_test, y_pred)
                mse = sklearn.metrics.mean_squared_error(y_test, y_pred)
                r2 = sklearn.metrics.r2_score(y_test, y_pred)

                regressor_table.add_data(
                    name,
                    round_3(mae),
                    round_3(mse),
                    round_3(r2)
                )
        elif getattr(estimator, "_estimator_type", None) == "clusterer":
            if X is not None:
                fig = plt.figure()
                ax = plt.axes()
                # Elbow curve
                scikitplot.cluster.plot_elbow_curve(estimator, X, ax=ax)
                wandb.log({prefix("elbow_curve"): fig}, commit=False)

                cluster_labels = estimator.fit_predict(X)

                fig = plt.figure()
                ax = plt.axes()
                # Silhouette plot
                scikitplot.metrics.plot_silhouette(X, cluster_labels, ax=ax)
                wandb.log({prefix("silhouette"): fig}, commit=False)
        counter += 1

    if len(classifier_table.data) > 0:
        wandb.log({"classifier_scores": classifier_table}, commit=False)
    if len(regressor_table.data) > 0:
        wandb.log({"regressor_scores": regressor_table}, commit=False)

    wandb.log({})

def plot_learning_curve(clf, X, y, title='Learning Curve', cv=None,
                        shuffle=False, random_state=None,
                        train_sizes=None, n_jobs=1, scoring=None,
                        ax=None, figsize=None, title_fontsize="large",
                        text_fontsize="medium"):
    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    if train_sizes is None:
        train_sizes = np.linspace(.1, 1.0, 5)

    ax.set_title(title, fontsize=title_fontsize)
    ax.set_xlabel("Training examples", fontsize=text_fontsize)
    ax.set_ylabel("Score", fontsize=text_fontsize)
    train_sizes, train_scores, test_scores = learning_curve(
        clf, X, y, cv=cv, n_jobs=n_jobs, train_sizes=train_sizes,
        scoring=scoring, shuffle=shuffle, random_state=random_state)
    train_scores_mean = np.mean(train_scores, axis=1)
    train_scores_std = np.std(train_scores, axis=1)
    test_scores_mean = np.mean(test_scores, axis=1)
    test_scores_std = np.std(test_scores, axis=1)

    # Take in data, return wandb.Table()
    def confusion(train, test, trainsize):
        return wandb.Table(
            columns=['train', 'test', 'train_size'],
            data=[
                [train[i], test[i], trainsize[i]] for i in range(len(train))
            ]
        )
    wandb.log({'learning_curve': confusion(train_scores_mean, test_scores_mean, train_sizes)})
    '''
    ax.grid()
    ax.plot(train_sizes, train_scores_mean, 'o-', color="r",
            label="Training score")
    ax.plot(train_sizes, test_scores_mean, 'o-', color="g",
            label="Cross-validation score")
    ax.tick_params(labelsize=text_fontsize)
    ax.legend(loc="best", fontsize=text_fontsize)
    '''
    return
