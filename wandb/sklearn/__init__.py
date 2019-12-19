import wandb
import sklearn
import scikitplot
import matplotlib.pyplot as plt

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
                scikitplot.estimators.plot_learning_curve(estimator, X, y, ax=ax)
                wandb.log({prefix("learning_curve"): fig}, commit=False)

                # scores["auc"] = sklearn.metrics.auc(X, y)
            if X_test is not None and y_test is not None:
                y_pred = estimator.predict(X_test)
                y_probas = estimator.predict_proba(X_test)

                fig = plt.figure()
                ax = plt.axes()
                scikitplot.metrics.plot_roc(y_test, y_probas, ax=ax)
                wandb.log({prefix("roc"): fig}, commit=False)

                fig = plt.figure()
                ax = plt.axes()
                scikitplot.metrics.plot_confusion_matrix(y_test, y_pred, ax=ax)
                wandb.log({prefix("confusion_matrix"): fig}, commit=False)

                classifier_table.add_data(
                    name,
                    round_3(sklearn.metrics.accuracy_score(y_test, y_pred)),
                    round_3(sklearn.metrics.precision_score(y_test, y_pred, average="weighted")),
                    round_3(sklearn.metrics.recall_score(y_test, y_pred, average="weighted")),
                    round_3(sklearn.metrics.f1_score(y_test, y_pred, average="weighted"))
                )
            if labels is not None:
                fig = plt.figure()
                ax = plt.axes()
                scikitplot.estimators.plot_feature_importances(estimator, feature_names=labels, ax=ax)
                wandb.log({prefix("feature_importances"): fig}, commit=False)
        elif sklearn.base.is_regressor(estimator):
            if X is not None and y is not None:
                fig = plt.figure()
                ax = plt.axes()
                scikitplot.estimators.plot_learning_curve(estimator, X, y, ax=ax)
                wandb.log({prefix("learning_curve"): fig}, commit=False)

            if X_test is not None and y_test is not None:
                y_pred = estimator.predict(X_test)

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
                scikitplot.cluster.plot_elbow_curve(estimator, X, ax=ax)
                wandb.log({prefix("elbow_curve"): fig}, commit=False)

                cluster_labels = estimator.fit_predict(X)

                fig = plt.figure()
                ax = plt.axes()
                scikitplot.metrics.plot_silhouette(X, cluster_labels, ax=ax)
                wandb.log({prefix("silhouette"): fig}, commit=False)
        counter += 1

    if len(classifier_table.data) > 0:
        wandb.log({"classifier_scores": classifier_table}, commit=False)
    if len(regressor_table.data) > 0:
        wandb.log({"regressor_scores": regressor_table}, commit=False)

    wandb.log({})
