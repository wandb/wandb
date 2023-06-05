from warnings import simplefilter

import numpy as np
import sklearn
from sklearn import model_selection, naive_bayes
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression

import wandb
from wandb.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def calibration_curves(clf, X, y, clf_name):
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

    model_column = []  # color
    frac_positives_column = []  # y axis
    mean_pred_value_column = []  # x axis
    hist_column = []  # barchart y
    edge_column = []  # barchart x

    # Add curve for perfectly calibrated model
    # format: model, fraction_of_positives, mean_predicted_value
    model_column.append("Perfectly calibrated")
    frac_positives_column.append(0)
    mean_pred_value_column.append(0)
    hist_column.append(0)
    edge_column.append(0)
    model_column.append("Perfectly calibrated")
    hist_column.append(0)
    edge_column.append(0)
    frac_positives_column.append(1)
    mean_pred_value_column.append(1)

    X_train, X_test, y_train, y_test = model_selection.train_test_split(
        X, y, test_size=0.9, random_state=42
    )

    # Add curve for LogisticRegression baseline and other models

    models = [lr, isotonic, sigmoid]
    names = ["Logistic", f"{clf_name} Isotonic", f"{clf_name} Sigmoid"]

    for model, name in zip(models, names):
        model.fit(X_train, y_train)
        if hasattr(model, "predict_proba"):
            prob_pos = model.predict_proba(X_test)[:, 1]
        else:  # use decision function
            prob_pos = model.decision_function(X_test)
            prob_pos = (prob_pos - prob_pos.min()) / (prob_pos.max() - prob_pos.min())

        hist, edges = np.histogram(prob_pos, bins=10, density=False)
        frac_positives, mean_pred_value = sklearn.calibration.calibration_curve(
            y_test, prob_pos, n_bins=10
        )

        # format: model, fraction_of_positives, mean_predicted_value
        num_entries = len(frac_positives)
        for i in range(num_entries):
            hist_column.append(hist[i])
            edge_column.append(edges[i])
            model_column.append(name)
            frac_positives_column.append(utils.round_3(frac_positives[i]))
            mean_pred_value_column.append(utils.round_3(mean_pred_value[i]))
            if utils.check_against_limit(
                i,
                "calibration_curve",
                utils.chart_limit - 2,
            ):
                break

    table = make_table(
        model_column,
        frac_positives_column,
        mean_pred_value_column,
        hist_column,
        edge_column,
    )
    chart = wandb.visualize("wandb/calibration/v1", table)

    return chart


def make_table(
    model_column,
    frac_positives_column,
    mean_pred_value_column,
    hist_column,
    edge_column,
):
    columns = [
        "model",
        "fraction_of_positives",
        "mean_predicted_value",
        "hist_dict",
        "edge_dict",
    ]

    data = list(
        zip(
            model_column,
            frac_positives_column,
            mean_pred_value_column,
            hist_column,
            edge_column,
        )
    )

    return wandb.Table(columns=columns, data=data)
