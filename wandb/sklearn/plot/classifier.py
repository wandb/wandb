"""Define plots for classification models built with scikit-learn."""

from warnings import simplefilter

import numpy as np
from sklearn import naive_bayes

import wandb
import wandb.plot
from wandb.sklearn import calculate, utils

from . import shared

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def classifier(
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
    """Generate all sklearn classifier plots supported by W&B.

    The following plots are generated:
        feature importances, confusion matrix, summary metrics,
        class proportions, calibration curve, roc curve, precision-recall curve.

    Should only be called with a fitted classifier (otherwise an error is thrown).

    Arguments:
        model: (classifier) Takes in a fitted classifier.
        X_train: (arr) Training set features.
        y_train: (arr) Training set labels.
        X_test: (arr) Test set features.
        y_test: (arr) Test set labels.
        y_pred: (arr) Test set predictions by the model passed.
        y_probas: (arr) Test set predicted probabilities by the model passed.
        labels: (list) Named labels for target variable (y). Makes plots easier to
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
    wandb.sklearn.plot_classifier(
        model,
        X_train,
        X_test,
        y_train,
        y_test,
        y_pred,
        y_probas,
        ["cat", "dog"],
        False,
        "RandomForest",
        ["barks", "drools", "plays_fetch", "breed"],
    )
    ```
    """
    wandb.termlog("\nPlotting %s." % model_name)

    if not isinstance(model, naive_bayes.MultinomialNB):
        feature_importances(model, feature_names)
        wandb.termlog("Logged feature importances.")

    if log_learning_curve:
        shared.learning_curve(model, X_train, y_train)
        wandb.termlog("Logged learning curve.")

    confusion_matrix(y_test, y_pred, labels)
    wandb.termlog("Logged confusion matrix.")

    shared.summary_metrics(model, X=X_train, y=y_train, X_test=X_test, y_test=y_test)
    wandb.termlog("Logged summary metrics.")

    class_proportions(y_train, y_test, labels)
    wandb.termlog("Logged class proportions.")

    if not isinstance(model, naive_bayes.MultinomialNB):
        calibration_curve(model, X_train, y_train, model_name)
        wandb.termlog("Logged calibration curve.")

    roc(y_test, y_probas, labels)
    wandb.termlog("Logged roc curve.")

    precision_recall(y_test, y_probas, labels)
    wandb.termlog("Logged precision-recall curve.")


def roc(
    y_true=None,
    y_probas=None,
    labels=None,
    plot_micro=True,
    plot_macro=True,
    classes_to_plot=None,
):
    """Log the receiver-operating characteristic curve.

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
    roc_chart = wandb.plot.roc_curve(y_true, y_probas, labels, classes_to_plot)
    wandb.log({"roc": roc_chart})


def confusion_matrix(
    y_true=None,
    y_pred=None,
    labels=None,
    true_labels=None,
    pred_labels=None,
    normalize=False,
):
    """Log a confusion matrix to W&B.

    Confusion matrices depict the pattern of misclassifications by a model.

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
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    not_missing = utils.test_missing(y_true=y_true, y_pred=y_pred)
    correct_types = utils.test_types(y_true=y_true, y_pred=y_pred)

    if not_missing and correct_types:
        confusion_matrix_chart = calculate.confusion_matrix(
            y_true,
            y_pred,
            labels,
            true_labels,
            pred_labels,
            normalize,
        )

        wandb.log({"confusion_matrix": confusion_matrix_chart})


def precision_recall(
    y_true=None, y_probas=None, labels=None, plot_micro=True, classes_to_plot=None
):
    """Log a precision-recall curve to W&B.

    Precision-recall curves depict the tradeoff between positive predictive value (precision)
    and true positive rate (recall) as the threshold of a classifier is shifted.

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
    precision_recall_chart = wandb.plot.pr_curve(
        y_true, y_probas, labels, classes_to_plot
    )

    wandb.log({"precision_recall": precision_recall_chart})


def feature_importances(
    model=None, feature_names=None, title="Feature Importance", max_num_features=50
):
    """Log a plot depicting the relative importance of each feature for a classifier's decisions.

    Should only be called with a fitted classifier (otherwise an error is thrown).
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
    wandb.sklearn.plot_feature_importances(model, ["width", "height", "length"])
    ```
    """
    not_missing = utils.test_missing(model=model)
    correct_types = utils.test_types(model=model)
    model_fitted = utils.test_fitted(model)

    if not_missing and correct_types and model_fitted:
        feature_importance_chart = calculate.feature_importances(model, feature_names)
        wandb.log({"feature_importances": feature_importance_chart})


def class_proportions(y_train=None, y_test=None, labels=None):
    """Plot the distribution of target classes in training and test sets.

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
    wandb.sklearn.plot_class_proportions(y_train, y_test, ["dog", "cat", "owl"])
    ```
    """
    not_missing = utils.test_missing(y_train=y_train, y_test=y_test)
    correct_types = utils.test_types(y_train=y_train, y_test=y_test)
    if not_missing and correct_types:
        y_train, y_test = np.array(y_train), np.array(y_test)
        class_proportions_chart = calculate.class_proportions(y_train, y_test, labels)

        wandb.log({"class_proportions": class_proportions_chart})


def calibration_curve(clf=None, X=None, y=None, clf_name="Classifier"):
    """Log a plot depicting how well-calibrated the predicted probabilities of a classifier are.

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

    Should only be called with a fitted classifier (otherwise an error is thrown).

    Please note this function fits variations of the model on the training set when called.

    Arguments:
        clf: (clf) Takes in a fitted classifier.
        X: (arr) Training set features.
        y: (arr) Training set labels.
        model_name: (str) Model name. Defaults to 'Classifier'

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
    wandb.sklearn.plot_calibration_curve(clf, X, y, "RandomForestClassifier")
    ```
    """
    not_missing = utils.test_missing(clf=clf, X=X, y=y)
    correct_types = utils.test_types(clf=clf, X=X, y=y)
    is_fitted = utils.test_fitted(clf)
    if not_missing and correct_types and is_fitted:
        y = np.asarray(y)
        if y.dtype.char == "U" or not ((y == 0) | (y == 1)).all():
            wandb.termwarn(
                "This function only supports binary classification at the moment and therefore expects labels to be binary. Skipping calibration curve."
            )
            return

        calibration_curve_chart = calculate.calibration_curves(clf, X, y, clf_name)

        wandb.log({"calibration_curve": calibration_curve_chart})
