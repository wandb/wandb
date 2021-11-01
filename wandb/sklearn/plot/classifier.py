"""Logs sklearn model plots to W&B."""
from warnings import simplefilter

import numpy as np
import sklearn
from sklearn import model_selection
import sklearn.calibration
from sklearn import naive_bayes
from sklearn.utils.multiclass import unique_labels
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression

import wandb
import wandb.plots

from wandb.sklearn import utils
from wandb.sklearn import calculate

from . import shared

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def DBPlot(*args, **kwargs):
    assert False  # FIXME


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
        wandb.sklearn.plot_classifier(model, X_train, X_test, y_train, y_test, y_pred, y_probas,
                                      ['cat', 'dog'], False, RandomForest',
                                      ['barks', 'drools, 'plays_fetch', 'breed'])
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
    """Logs the receiver-operating characteristic curve.

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
        {
            "roc": wandb.plots.roc(
                y_true, y_probas, labels, plot_micro, plot_macro, classes_to_plot
            )
        }
    )


def confusion_matrix(
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
    """Logs a confusion matrix to W&B.

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


def precision_recall(
    y_true=None, y_probas=None, labels=None, plot_micro=True, classes_to_plot=None
):
    """Logs a precision-recall curve to W&B.

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
    wandb.log(
        {
            "precision_recall": wandb.plots.precision_recall(
                y_true, y_probas, labels, plot_micro, classes_to_plot
            )
        }
    )


def feature_importances(
    model=None, feature_names=None, title="Feature Importance", max_num_features=50
):
    """Logs a plot depicting the relative importance of each feature for a classifier's decisions.

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


def class_proportions(y_train=None, y_test=None, labels=None):
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
        y_train, y_test = np.array(y_train), np.array(y_test)
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


def calibration_curve(clf=None, X=None, y=None, clf_name="Classifier"):
    """Logs a plot depicting how well-calibrated the predicted probabilities of a classifier are.

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

            (
                fraction_of_positives,
                mean_predicted_value,
            ) = sklearn.calibration.calibration_curve(y_test, prob_pos, n_bins=10)
            hist, edges = np.histogram(prob_pos, bins=10, density=False)

            # format: model, fraction_of_positives, mean_predicted_value
            for i in range(len(fraction_of_positives)):
                hist_dict.append(hist[i])
                edge_dict.append(edges[i])
                model_dict.append(name)
                frac_positives_dict.append(utils.round_3(fraction_of_positives[i]))
                mean_pred_value_dict.append(utils.round_3(mean_predicted_value[i]))
                if utils.check_against_limit(
                    i, utils.chart_limit - 2, "calibration_curve"
                ):
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


def decision_boundaries(binary_clf=None, X=None, y=None):
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
