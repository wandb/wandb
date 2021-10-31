"""Logs sklearn model plots to W&B."""
from warnings import simplefilter

import numpy as np
import pandas as pd
import sklearn
from sklearn import model_selection
from sklearn.metrics import silhouette_score, silhouette_samples
from sklearn.preprocessing import LabelEncoder
from sklearn.calibration import calibration_curve
from sklearn import naive_bayes
from sklearn.utils.multiclass import unique_labels
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression

import wandb
from wandb.plots.roc import roc
from wandb.plots.precision_recall import precision_recall

from wandb.sklearn import utils
from wandb.sklearn import calculate

from fakemodule import DBPlot  # TODO: fix

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def plot_classifier(
    model,
    X_train,
    X_test,
    y_train,
    y_test,
    y_pred,
    y_probas,
    labels,
    is_binary=False,
    model_name="Classifier",
    feature_names=None,
    log_learning_curve=False,
):
    """Generates all sklearn classifier plots supported by W&B.

    The following plots are generated:
        feature importances, confusion matrix, summary metrics,
        class balance plot, calibration curve, roc curve, precision-recall curve.

    Should only be called with a fitted classifer (otherwise an error is thrown).

    Arguments:
        model: (classifier) Takes in a fitted classifier.
        X_train: (arr) Training set features.
        y_train: (arr) Training set labels.
        X_test: (arr) Test set features.
        y_test: (arr) Test set labels.
        y_pred: (arr) Test set predictions by the model passed.
        y_probas: (arr) Test set predicted probabilities by the model passed.
        labels: (list) Named labels for target varible (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example if `labels=['dog', 'cat', 'owl']` all 0s are
                        replaced by dog, 1s by cat.
        is_binary: (bool) Is the model passed a binary classifier? Defaults to False
        model_name: (str) Model name. Defaults to 'Classifier'
        feature_names: (list) Names for features. Makes plots easier to read by
                                replacing feature indexes with corresponding names.
        log_learning_curve: (bool) Whether or not to log the learning curve.
                                    Defaults to False.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
            under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_classifier(model, X_train, X_test, y_train, y_test,
                        y_pred, y_probas, ['cat', 'dog'], False,
                        'RandomForest', ['barks', 'drools, 'plays_fetch', 'breed'])
    ```
    """
    wandb.termlog("\nPlotting %s." % model_name)
    if not isinstance(model, naive_bayes.MultinomialNB):
        plot_feature_importances(model, feature_names)
        wandb.termlog("Logged feature importances.")
    if log_learning_curve:
        plot_learning_curve(model, X_train, y_train)
        wandb.termlog("Logged learning curve.")
    plot_confusion_matrix(y_test, y_pred, labels)
    wandb.termlog("Logged confusion matrix.")
    plot_summary_metrics(model, X=X_train, y=y_train, X_test=X_test, y_test=y_test)
    wandb.termlog("Logged summary metrics.")
    plot_class_proportions(y_train, y_test, labels)
    wandb.termlog("Logged class proportions.")
    if not isinstance(model, naive_bayes.MultinomialNB):
        plot_calibration_curve(model, X_train, y_train, model_name)
        wandb.termlog("Logged calibration curve.")
    plot_roc(y_test, y_probas, labels)
    wandb.termlog("Logged roc curve.")
    plot_precision_recall(y_test, y_probas, labels)
    wandb.termlog("Logged precision recall curve.")
    # if is_binary:
    # plot_decision_boundaries(model, X_train, y_train)
    # wandb.termlog('Logged decision boundary plot.')


def plot_regressor(model, X_train, X_test, y_train, y_test, model_name="Regressor"):
    """Generates all sklearn regressor plots supported by W&B.

    The following plots are generated:
        learning curve, summary metrics, residuals plot, outlier candidates.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Arguments:
        model: (regressor) Takes in a fitted regressor.
        X_train: (arr) Training set features.
        y_train: (arr) Training set labels.
        X_test: (arr) Test set features.
        y_test: (arr) Test set labels.
        model_name: (str) Model name. Defaults to 'Regressor'

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
            under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_regressor(reg, X_train, X_test, y_train, y_test, 'Ridge')
    ```
    """
    wandb.termlog("\nPlotting %s." % model_name)
    plot_summary_metrics(model, X_train, y_train, X_test, y_test)
    wandb.termlog("Logged summary metrics.")
    plot_learning_curve(model, X_train, y_train)
    wandb.termlog("Logged learning curve.")
    plot_outlier_candidates(model, X_train, y_train)
    wandb.termlog("Logged outlier candidates.")
    plot_residuals(model, X_train, y_train)
    wandb.termlog("Logged residuals.")


def plot_clusterer(model, X_train, cluster_labels, labels=None, model_name="Clusterer"):
    """Generates all sklearn clusterer plots supported by W&B.

    The following plots are generated:
        elbow curve, silhouette plot.

    Should only be called with a fitted clusterer (otherwise an error is thrown).

    Arguments:
        model: (clusterer) Takes in a fitted clusterer.
        X_train: (arr) Training set features.
        cluster_labels: (list) Names for cluster labels. Makes plots easier to read
                            by replacing cluster indexes with corresponding names.
        labels: (list) Named labels for target varible (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example if `labels=['dog', 'cat', 'owl']` all 0s are
                        replaced by dog, 1s by cat.
        model_name: (str) Model name. Defaults to 'Clusterer'

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_clusterer(kmeans, X, cluster_labels, labels, 'KMeans')
    ```
    """
    wandb.termlog("\nPlotting %s." % model_name)
    if isinstance(model, sklearn.cluster.KMeans):
        plot_elbow_curve(model, X_train)
        wandb.termlog("Logged elbow curve.")
        plot_silhouette(model, X_train, cluster_labels, labels=labels, kmeans=True)
    else:
        plot_silhouette(model, X_train, cluster_labels, kmeans=False)
    wandb.termlog("Logged silhouette plot.")


def plot_summary_metrics(model=None, X=None, y=None, X_test=None, y_test=None):
    """Logs the charts generated by summary_metrics in wandb.

    Should only be called with a fitted model (otherwise an error is thrown).

    Arguments:
        model: (clf or reg) Takes in a fitted regressor or classifier.
        X: (arr) Training set features.
        y: (arr) Training set labels.
        X_test: (arr) Test set features.
        y_test: (arr) Test set labels.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_summary_metrics(model, X_train, y_train, X_test, y_test)
    """
    wandb.log(
        {"summary_metrics": calculate.summary_metrics(model, X, y, X_test, y_test)}
    )


def plot_learning_curve(
    model=None,
    X=None,
    y=None,
    cv=None,
    shuffle=False,
    random_state=None,
    train_sizes=None,
    n_jobs=1,
    scoring=None,
):
    """Logs the plots generated by learning_curve() to wandb.

    Please note this function fits the model to datasets of varying sizes when called.

    Arguments:
        model: (clf or reg) Takes in a fitted regressor or classifier.
        X: (arr) Dataset features.
        y: (arr) Dataset labels.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_learning_curve(model, X, y)
    ```
    """
    wandb.log(
        {
            "learning_curve": calculate.learning_curve(
                model, X, y, cv, shuffle, random_state, train_sizes, n_jobs, scoring
            )
        }
    )


def plot_roc(
    y_true=None,
    y_probas=None,
    labels=None,
    plot_micro=True,
    plot_macro=True,
    classes_to_plot=None,
):
    """Logs the plots generated by roc() to wandb.

    Arguments:
        y_true: (arr) Test set labels.
        y_probas: (arr) Test set predicted probabilities.
        labels: (list) Named labels for target variable (y). Makes plots easier to
                       read by replacing target values with corresponding index.
                       For example if `labels=['dog', 'cat', 'owl']` all 0s are
                       replaced by dog, 1s by cat.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_roc(y_true, y_probas, labels)
    ```
    """
    wandb.log(
        {"roc": roc(y_true, y_probas, labels, plot_micro, plot_macro, classes_to_plot)}
    )


def plot_confusion_matrix(
    y_true=None,
    y_pred=None,
    labels=None,
    true_labels=None,
    pred_labels=None,
    title=None,
    normalize=False,
    hide_zeros=False,
    hide_counts=False,
):
    """Logs the plots generated by confusion_matrix() to wandb.

    Arguments:
        y_true: (arr) Test set labels.
        y_probas: (arr) Test set predicted probabilities.
        labels: (list) Named labels for target variable (y). Makes plots easier to
                       read by replacing target values with corresponding index.
                       For example if `labels=['dog', 'cat', 'owl']` all 0s are
                       replaced by dog, 1s by cat.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_confusion_matrix(y_true, y_probas, labels)
    ```
    """
    wandb.log(
        {
            "confusion_matrix": calculate.confusion_matrix(
                y_true,
                y_pred,
                labels,
                true_labels,
                pred_labels,
                title,
                normalize,
                hide_zeros,
                hide_counts,
            )
        }
    )


def plot_precision_recall(
    y_true=None, y_probas=None, labels=None, plot_micro=True, classes_to_plot=None
):
    """Logs the plots generated by precision_recall() to wandb.

    Arguments:
        y_true: (arr) Test set labels.
        y_probas: (arr) Test set predicted probabilities.
        labels: (list) Named labels for target variable (y). Makes plots easier to
                       read by replacing target values with corresponding index.
                       For example if `labels=['dog', 'cat', 'owl']` all 0s are
                       replaced by dog, 1s by cat.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_precision_recall(y_true, y_probas, labels)
    ```
    """
    wandb.log(
        {
            "precision_recall": precision_recall(
                y_true, y_probas, labels, plot_micro, classes_to_plot
            )
        }
    )


def plot_feature_importances(
    model=None, feature_names=None, title="Feature Importance", max_num_features=50
):
    """Evaluates & plots the importance of each feature for a classifier.

    Should only be called with a fitted classifer (otherwise an error is thrown).
    Only works with classifiers that have a feature_importances_ attribute, like trees.

    Arguments:
        model: (clf) Takes in a fitted classifier.
        feature_names: (list) Names for features. Makes plots easier to read by
                              replacing feature indexes with corresponding names.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_feature_importances(model, ['width', 'height, 'length'])
    ```
    """
    attributes_to_check = ["feature_importances_", "feature_log_prob_", "coef_"]
    found_attribute = check_for_attribute_on(model)
    if found_attribute is None:
        wandb.termwarn(
            f"could not find any of attributes {attributes_to_check} on classifier. Cannot plot feature importances."
        )
        return

    if (
        utils.test_missing(model=model)
        and utils.test_types(model=model)
        and utils.test_fitted(model)
    ):
        if found_attribute == "feature_importances_":
            importances = model.feature_importances_
        elif found_attribute == "coef_":  # ElasticNet or ElasticNetCV like models
            importances = model.coef_
        elif found_attribute == "feature_log_prob_":
            # coef_ was deprecated in sklearn 0.24, replaced with
            # feature_log_prob_
            importances = model.feature_log_prob_

        if len(importances.shape) > 1:
            if np.prod(importances.shape) > importances.shape[0]:
                nd = len(importances.shape)
                wandb.termwarn(
                    f"{nd}-dimensional feature importances array passed to plot_feature_importances. "
                    f"{nd}-dimensional and higher feature importances arrays are not currently supported. "
                    f"These importances will not be plotted."
                )
                return
            else:
                importances = np.squeeze(importances)

        indices = np.argsort(importances)[::-1]
        importances = importances[indices]

        if feature_names is None:
            feature_names = indices
        else:
            feature_names = np.array(feature_names)[indices]

        max_num_features = min(max_num_features, len(importances))

        wandb.log(
            {
                "feature_importances": calculate.make_feature_importances_table(
                    feature_names, importances
                )
            }
        )


def plot_elbow_curve(
    clusterer=None, X=None, cluster_ranges=None, n_jobs=1, show_cluster_time=True
):
    """Measures and plots variance explained as a function of the number of clusters.

    Useful in picking the optimal number of clusters.

    Should only be called with a fitted clusterer (otherwise an error is thrown).

    Please note this function fits the model on the training set when called.

    Arguments:
        model: (clusterer) Takes in a fitted clusterer.
        X: (arr) Training set features.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_elbow_curve(model, X_train)
    ```
    """
    if not hasattr(clusterer, "n_clusters"):
        wandb.termlog(
            "n_clusters attribute not in classifier. Cannot plot elbow method."
        )
        return
    if (
        utils.test_missing(clusterer=clusterer)
        and utils.test_types(clusterer=clusterer)
        and utils.test_fitted(clusterer)
    ):
        try:
            from joblib import Parallel, delayed
        except ImportError:
            wandb.termerror("plot_elbow_curve requires python 3x")
            return
        if cluster_ranges is None:
            cluster_ranges = range(1, 10, 2)
        else:
            cluster_ranges = sorted(cluster_ranges)

        if not hasattr(clusterer, "n_clusters"):
            raise TypeError(
                '"n_clusters" attribute not in classifier. ' "Cannot plot elbow method."
            )

        tuples = Parallel(n_jobs=n_jobs)(
            delayed(calculate._clone_and_score_clusterer)(clusterer, X, i)
            for i in cluster_ranges
        )
        clfs, times = zip(*tuples)

        clfs = np.absolute(clfs)

        # Elbow curve
        # ax.plot(cluster_ranges, np.absolute(clfs), 'b*-')

        # Cluster time
        # ax2.plot(cluster_ranges, times, ':', alpha=0.75, color=ax2_color)

        # format:
        # cluster_ranges - x axis
        # errors = clfs - y axis
        # clustering_time = times - y axis2

        wandb.log(
            {
                "elbow_curve": calculate.make_elbow_curve_table(
                    cluster_ranges, clfs, times
                )
            }
        )
        return


def plot_silhouette(
    clusterer=None,
    X=None,
    cluster_labels=None,
    labels=None,
    metric="euclidean",
    kmeans=True,
):
    """Measures & plots silhouette coefficients.

    Silhouette coefficients near +1 indicate that the sample is far away from
    the neighboring clusters. A value near 0 indicates that the sample is on or
    very close to the decision boundary between two neighboring clusters and
    negative values indicate that the samples might have been assigned to the wrong cluster.

    Should only be called with a fitted clusterer (otherwise an error is thrown).

    Please note this function fits the model on the training set when called.

    Arguments:
        model: (clusterer) Takes in a fitted clusterer.
        X: (arr) Training set features.
        cluster_labels: (list) Names for cluster labels. Makes plots easier to read
                               by replacing cluster indexes with corresponding names.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_silhouette(model, X_train, ['spam', 'not spam'])
    ```
    """
    if (
        utils.test_missing(clusterer=clusterer)
        and utils.test_types(clusterer=clusterer)
        and utils.test_fitted(clusterer)
    ):
        if isinstance(X, (pd.DataFrame)):
            X = X.values
        # Run clusterer for n_clusters in range(len(cluster_ranges), get cluster labels
        # TODO - keep/delete once we decide if we should train clusterers
        # or ask for trained models
        # clusterer.set_params(n_clusters=n_clusters, random_state=42)
        # cluster_labels = clusterer.fit_predict(X)
        cluster_labels = np.asarray(cluster_labels)
        labels = np.asarray(labels)

        le = LabelEncoder()
        _ = le.fit_transform(cluster_labels)
        n_clusters = len(np.unique(cluster_labels))

        # The silhouette_score gives the average value for all the samples.
        # This gives a perspective into the density and separation of the formed
        # clusters
        silhouette_avg = silhouette_score(X, cluster_labels, metric=metric)

        # Compute the silhouette scores for each sample
        sample_silhouette_values = silhouette_samples(X, cluster_labels, metric=metric)

        # Plot 1: Silhouette Score
        # y = np.arange(y_lower, y_upper)[]
        # x1 = 0
        # x2 = ith_cluster_silhouette_values[]
        # color = le.classes_[n_clusters]
        # rule_line = silhouette_avg

        y_sil = []
        x_sil = []
        color_sil = []

        y_lower = 10
        count = 0
        for i in range(n_clusters):
            # Aggregate the silhouette scores for samples belonging to
            # cluster i, and sort them
            ith_cluster_silhouette_values = sample_silhouette_values[
                cluster_labels == i
            ]

            ith_cluster_silhouette_values.sort()

            size_cluster_i = ith_cluster_silhouette_values.shape[0]
            y_upper = y_lower + size_cluster_i

            y_values = np.arange(y_lower, y_upper)

            for j in range(len(y_values)):
                y_sil.append(y_values[j])
                x_sil.append(ith_cluster_silhouette_values[j])
                color_sil.append(i)
                count += 1
                if utils.check_against_limit(count, CHART_LIMIT, "silhouette"):
                    break

            # Compute the new y_lower for next plot
            y_lower = y_upper + 10  # 10 for the 0 samples

        # Plot 2: Scatter Plot showing the actual clusters formed
        if kmeans:
            centers = clusterer.cluster_centers_

            wandb_key = "silhouette_plot"
            wandb.log(
                {
                    wandb_key: calculate.silhouette(
                        X[:, 0],
                        X[:, 1],
                        cluster_labels,
                        centers[:, 0],
                        centers[:, 1],
                        y_sil,
                        x_sil,
                        color_sil,
                        silhouette_avg,
                    )
                }
            )
        else:
            centerx = [None] * len(color_sil)
            centery = [None] * len(color_sil)

            wandb_key = "silhouette_plot"
            wandb.log(
                {
                    wandb_key: calculate.silhouette_(
                        X[:, 0],
                        X[:, 1],
                        cluster_labels,
                        centerx,
                        centery,
                        y_sil,
                        x_sil,
                        color_sil,
                        silhouette_avg,
                    )
                }
            )
        return


def plot_class_proportions(y_train=None, y_test=None, labels=None):
    """Plots the distribution of target classses in training and test sets.

    Useful for detecting imbalanced classes.

    Arguments:
        y_train: (arr) Training set labels.
        y_test: (arr) Test set labels.
        labels: (list) Named labels for target variable (y). Makes plots easier to
                       read by replacing target values with corresponding index.
                       For example if `labels=['dog', 'cat', 'owl']` all 0s are
                       replaced by dog, 1s by cat.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_class_proportions(y_train, y_test, ['dog', 'cat', 'owl'])
    ```
    """
    if utils.test_missing(y_train=y_train, y_test=y_test) and utils.test_types(
        y_train=y_train, y_test=y_test
    ):
        # Get the unique values from the dataset
        y_train = np.array(y_train)
        y_test = np.array(y_test)
        targets = (y_train,) if y_test is None else (y_train, y_test)
        classes_ = np.array(unique_labels(*targets))

        # Compute the class counts
        class_counts_train = np.array([(y_train == c).sum() for c in classes_])
        class_counts_test = np.array([(y_test == c).sum() for c in classes_])

        wandb.log(
            {
                "class_proportions": calculate.class_proportions(
                    classes_, class_counts_train, class_counts_test
                )
            }
        )


def plot_calibration_curve(clf=None, X=None, y=None, clf_name="Classifier"):
    """Plots how well-calibrated the predicted probabilities of a classifier are.

    Also suggests how to calibrate an uncalibrated classifier. Compares estimated predicted
    probabilities by a baseline logistic regression model, the model passed as
    an argument, and by both its isotonic calibration and sigmoid calibrations.
    The closer the calibration curves are to a diagonal the better.
    A sine wave like curve represents an overfitted classifier, while a cosine
    wave like curve represents an underfitted classifier.
    By training isotonic and sigmoid calibrations of the model and comparing
    their curves we can figure out whether the model is over or underfitting and
    if so which calibration (sigmoid or isotonic) might help fix this.
    For more details, see https://scikit-learn.org/stable/auto_examples/calibration/plot_calibration_curve.html.

    Should only be called with a fitted classifer (otherwise an error is thrown).

    Please note this function fits variations of the model on the training set when called.

    Arguments:
        model: (clf) Takes in a fitted classifier.
        X: (arr) Training set features.
        y: (arr) Training set labels.
        model_name: (str) Model name. Defaults to 'Classifier'

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_calibration_curve(clf, X, y, 'RandomForestClassifier')
    ```
    """
    if (
        utils.test_missing(clf=clf, X=X, y=y)
        and utils.test_types(clf=clf, X=X, y=y)
        and utils.test_fitted(clf)
    ):
        y = np.asarray(y)
        if not ((y == 0) | (y == 1)).all():
            raise ValueError(
                "This function only supports binary classification at the moment and therefore expects labels to be binary."
            )

        # ComplementNB (introduced in 0.20.0) requires non-negative features
        if int(sklearn.__version__.split(".")[1]) >= 20 and isinstance(
            clf, naive_bayes.ComplementNB
        ):
            X = X - X.min()

        # Calibrated with isotonic calibration
        isotonic = CalibratedClassifierCV(clf, cv=2, method="isotonic")

        # Calibrated with sigmoid calibration
        sigmoid = CalibratedClassifierCV(clf, cv=2, method="sigmoid")

        # Logistic regression with no calibration as baseline
        lr = LogisticRegression(C=1.0)

        model_dict = []  # color
        frac_positives_dict = []  # y axis
        mean_pred_value_dict = []  # x axis
        hist_dict = []  # barchart y
        edge_dict = []  # barchart x

        # Add curve for perfectly calibrated model
        # format: model, fraction_of_positives, mean_predicted_value
        model_dict.append("Perfectly calibrated")
        frac_positives_dict.append(0)
        mean_pred_value_dict.append(0)
        hist_dict.append(0)
        edge_dict.append(0)
        model_dict.append("Perfectly calibrated")
        hist_dict.append(0)
        edge_dict.append(0)
        frac_positives_dict.append(1)
        mean_pred_value_dict.append(1)

        X_train, X_test, y_train, y_test = model_selection.train_test_split(
            X, y, test_size=0.98, random_state=42
        )

        # Add curve for LogisticRegression baseline and other models

        for model, name in [
            (lr, "Logistic"),
            (isotonic, clf_name + " + Isotonic"),
            (sigmoid, clf_name + " + Sigmoid"),
        ]:
            model.fit(X_train, y_train)
            if hasattr(model, "predict_proba"):
                prob_pos = model.predict_proba(X_test)[:, 1]
            else:  # use decision function
                prob_pos = model.decision_function(X_test)
                prob_pos = (prob_pos - prob_pos.min()) / (
                    prob_pos.max() - prob_pos.min()
                )

            fraction_of_positives, mean_predicted_value = calibration_curve(
                y_test, prob_pos, n_bins=10
            )
            hist, edges = np.histogram(prob_pos, bins=10, density=False)

            # format: model, fraction_of_positives, mean_predicted_value
            for i in range(len(fraction_of_positives)):
                hist_dict.append(hist[i])
                edge_dict.append(edges[i])
                model_dict.append(name)
                frac_positives_dict.append(utils.round_3(fraction_of_positives[i]))
                mean_pred_value_dict.append(utils.round_3(mean_predicted_value[i]))
                if utils.check_against_limit(i, CHART_LIMIT - 2, "calibration_curve"):
                    break

        wandb.log(
            {
                "calibration_curve": calculate.calibration_curves(
                    model_dict,
                    frac_positives_dict,
                    mean_pred_value_dict,
                    hist_dict,
                    edge_dict,
                )
            }
        )


def plot_outlier_candidates(regressor=None, X=None, y=None):
    """Measures a datapoint's influence on regression model via cook's distance.

    Instances with high influences could potentially be outliers.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Please note this function fits the model on the training set when called.

    Arguments:
        model: (regressor) Takes in a fitted regressor.
        X: (arr) Training set features.
        y: (arr) Training set labels.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_outlier_candidates(model, X, y)
    ```
    """
    if (
        utils.test_missing(regressor=regressor, X=X, y=y)
        and utils.test_types(regressor=regressor, X=X, y=y)
        and utils.test_fitted(regressor)
    ):
        y = np.asarray(y)
        # Fit a linear model to X and y to compute MSE
        regressor.fit(X, y)

        # Leverage is computed as the diagonal of the projection matrix of X
        leverage = (X * np.linalg.pinv(X).T).sum(1)

        # Compute the rank and the degrees of freedom of the OLS model
        rank = np.linalg.matrix_rank(X)
        df = X.shape[0] - rank

        # Compute the MSE from the residuals
        residuals = y - regressor.predict(X)
        mse = np.dot(residuals, residuals) / df

        # Compute Cook's distance
        residuals_studentized = residuals / np.sqrt(mse) / np.sqrt(1 - leverage)
        distance_ = residuals_studentized ** 2 / X.shape[1]
        distance_ *= leverage / (1 - leverage)

        # Compute the influence threshold rule of thumb
        influence_threshold_ = 4 / X.shape[0]
        outlier_percentage_ = sum(distance_ >= influence_threshold_) / X.shape[0]
        outlier_percentage_ *= 100.0

        distance_dict = []
        count = 0
        for d in distance_:
            distance_dict.append(d)
            count += 1
            if utils.check_against_limit(count, CHART_LIMIT, "outlier_candidates"):
                break

        wandb.log(
            {
                "outlier_candidates": calculate.outlier_candidates(
                    distance_dict, outlier_percentage_, influence_threshold_
                )
            }
        )
        return


def plot_residuals(regressor=None, X=None, y=None):
    """Measures and plots the regressor's predicted value against the residual.

    The marginal distribution of residuals is also calculated and plotted.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Please note this function fits variations of the model on the training set when called.

    Arguments:
        model: (regressor) Takes in a fitted regressor.
        X: (arr) Training set features.
        y: (arr) Training set labels.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_residuals(model, X, y)
    ```
    """
    if (
        utils.test_missing(regressor=regressor, X=X, y=y)
        and utils.test_types(regressor=regressor, X=X, y=y)
        and utils.test_fitted(regressor)
    ):
        y = np.asarray(y)
        # Create the train and test splits
        X_train, X_test, y_train, y_test = model_selection.train_test_split(
            X, y, test_size=0.2
        )

        # Store labels and colors for the legend ordered by call
        regressor.fit(X_train, y_train)
        train_score_ = regressor.score(X_train, y_train)
        test_score_ = regressor.score(X_test, y_test)

        y_pred_train = regressor.predict(X_train)
        residuals_train = y_pred_train - y_train

        y_pred_test = regressor.predict(X_test)
        residuals_test = y_pred_test - y_test

        wandb.log(
            {
                "residuals": calculate.residuals(
                    y_pred_train,
                    residuals_train,
                    y_pred_test,
                    residuals_test,
                    train_score_,
                    test_score_,
                )
            }
        )


def plot_decision_boundaries(binary_clf=None, X=None, y=None):
    """Visualizes decision boundaries of a binary classifier.

    Works by sampling from the feature space where the classifier's uncertainty
    if greater than > 0.5 and projecting these point to 2D space.

     Useful for measuring model (decision boundary) complexity, visualizing
     regions where the model falters, and to determine whether any over or
     underfitting occured.

    Should only be called with a fitted **binary** classifer (otherwise an error is
    thrown). Please note this function fits variations of the model on the
    training set when called.

    Arguments:
        model: (clf) Takes in a fitted binary classifier.
        X_train: (arr) Training set features.
        y_train: (arr) Training set labels.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_decision_boundaries(binary_classifier, X, y)
    ```
    """
    if utils.test_missing(binary_clf=binary_clf, X=X, y=y) and utils.test_types(
        binary_clf=binary_clf, X=X, y=y
    ):
        y = np.asarray(y)
        # plot high-dimensional decision boundary
        db = DBPlot(binary_clf)
        db = None
        db.fit(X, y)
        (
            decision_boundary_x,
            decision_boundary_y,
            decision_boundary_color,
            train_x,
            train_y,
            train_color,
            test_x,
            test_y,
            test_color,
        ) = db.plot()

        wandb.log(
            {
                "decision_boundaries": calculate.decision_boundaries(
                    decision_boundary_x,
                    decision_boundary_y,
                    decision_boundary_color,
                    train_x,
                    train_y,
                    train_color,
                    test_x,
                    test_y,
                    test_color,
                )
            }
        )


def check_for_attribute_on(model, attributes_to_check):
    for attr in attributes_to_check:
        if hasattr(model, attr):
            return attr
    return None
