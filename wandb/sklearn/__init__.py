from __future__ import absolute_import, division, print_function, unicode_literals
import wandb
import itertools
import sklearn
import numpy as np
import scipy as sp
import scikitplot
import matplotlib.pyplot as plt
from keras.callbacks import LambdaCallback
from sklearn import model_selection
from sklearn.model_selection import train_test_split
from sklearn import metrics
from sklearn.preprocessing import label_binarize
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import roc_curve
from sklearn.metrics import auc
from sklearn.metrics import precision_recall_curve
from sklearn.metrics import average_precision_score
from sklearn.metrics import (brier_score_loss, precision_score, recall_score, f1_score)
from sklearn.utils.multiclass import unique_labels
from sklearn.metrics import silhouette_score
from sklearn.metrics import silhouette_samples
from sklearn.calibration import calibration_curve
from sklearn.utils.multiclass import unique_labels, type_of_target
from sklearn import datasets
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV, calibration_curve

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
                plot_roc(y_test, y_probas)

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

                # Class Balance Plot
                plot_class_balance(y, y_test, labels)

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
                plot_learning_curve(estimator, X, y)

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

def learning_curve(clf, X, y, cv=None,
                        shuffle=False, random_state=None,
                        train_sizes=None, n_jobs=1, scoring=None):
    if train_sizes is None:
        train_sizes = np.linspace(.1, 1.0, 5)

    train_sizes, train_scores, test_scores = model_selection.learning_curve(
        clf, X, y, cv=cv, n_jobs=n_jobs, train_sizes=train_sizes,
        scoring=scoring, shuffle=shuffle, random_state=random_state)
    train_scores_mean = np.mean(train_scores, axis=1)
    train_scores_std = np.std(train_scores, axis=1)
    test_scores_mean = np.mean(test_scores, axis=1)
    test_scores_std = np.std(test_scores, axis=1)

    def learning_curve_table(train, test, trainsize):
        data=[]
        for i in range(len(train)):
            train_set = ["train", round(train[i],2), trainsize[i]]
            test_set = ["test", round(test[i],2), trainsize[i]]
            data.append(train_set)
            data.append(test_set)
        return wandb.Table(
            columns=['dataset', 'score', 'train_size'],
            data=data
        )

    return learning_curve_table(train_scores_mean, test_scores_mean, train_sizes)

def plot_learning_curve(clf, X, y, cv=None,
                        shuffle=False, random_state=None,
                        train_sizes=None, n_jobs=1, scoring=None):
  wandb.log({'learning_curve': learning_curve(clf, X, y, title, cv, shuffle,
      random_state, train_sizes, n_jobs, scoring)})


'''
    l2k2/sklearn_learningcurve

    {
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "padding": 5,
  "width": "500",
  "height": "500",
  "data":
    {
      "name": "${history-table:rows:x-axis,key}"
    },
  "title": {
    "text": "Learning Curve"
  },"layer": [
    {
      "encoding": {
        "x": {"field": "train_size", "type": "quantitative"},
        "y": {"field": "score", "type": "quantitative"},
        "color": {"field": "dataset", "type": "nominal"}
      },
      "layer": [
        {"mark": "line"},
        {
          "selection": {
            "label": {
              "type": "single",
              "nearest": true,
              "on": "mouseover",
              "encodings": ["x"],
              "empty": "none"
            }
          },
          "mark": "point",
          "encoding": {
            "opacity": {
              "condition": {"selection": "label", "value": 1},
              "value": 0
            }
          }
        }
      ]
    },
    {
      "transform": [{"filter": {"selection": "label"}}],
      "layer": [
        {
          "mark": {"type": "rule", "color": "gray"},
          "encoding": {
            "x": {"type": "quantitative", "field": "train_size"}
          }
        },
        {
          "encoding": {
            "text": {"type": "quantitative", "field": "score"},
            "x": {"type": "quantitative", "field": "train_size"},
            "y": {"type": "quantitative", "field": "score"}
          },
          "layer": [
            {
              "mark": {
                "type": "text",
                "stroke": "white",
                "strokeWidth": 2,
                "align": "left",
                "dx": 5,
                "dy": -5
              }
            },
            {
              "mark": {"type": "text", "align": "left", "dx": 5, "dy": -5},
              "encoding": {
                "color": {
                  "type": "nominal", "field": "dataset", "scale": {
                  "domain": ["train", "test"],
                  "range": ["#3498DB", "#AB47BC"]
                  },
                  "legend": {
                  "title": " "
                  }
                }
              }
            }
          ]
        }
      ]
    }
  ]
}
'''

def roc(y_true, y_probas,
                   plot_micro=True, plot_macro=True, classes_to_plot=None,
                   ):
    y_true = np.array(y_true)
    y_probas = np.array(y_probas)
    classes = np.unique(y_true)
    probas = y_probas

    if classes_to_plot is None:
        classes_to_plot = classes

    fpr_dict = dict()
    tpr_dict = dict()

    indices_to_plot = np.in1d(classes, classes_to_plot)

    def roc_table(fpr_dict, tpr_dict, classes, indices_to_plot):
        data=[]

        for i, to_plot in enumerate(indices_to_plot):
            print(probas.shape)
            fpr_dict[i], tpr_dict[i], _ = roc_curve(y_true, probas[:, i],
                                                    pos_label=classes[i])
            if to_plot:
                roc_auc = auc(fpr_dict[i], tpr_dict[i])
                for j in range(len(fpr_dict[i])):
                    fpr = [classes[i], fpr_dict[i][j], tpr_dict[i][j]]
                    data.append(fpr)
        return wandb.Table(
            columns=['class', 'fpr', 'tpr'],
            data=data
        )
    return roc_table(fpr_dict, tpr_dict, classes, indices_to_plot)

def plot_roc(y_true, y_probas,
                   plot_micro=True, plot_macro=True, classes_to_plot=None,
                   ):
  wandb.log({'roc': roc(y_true, y_probas,
                   plot_micro, plot_macro, classes_to_plot)})


#    {
#   "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
#   "padding": 5,
#   "width": "500",
#   "height": "500",
#   "data":
#     {
#       "name": "${history-table:rows:x-axis,key}"
#     },
#   "title": {
#     "text": "Learning Curve"
#   },"layer": [
#     {
#       "encoding": {
#         "x": {"field": "fpr", "type": "quantitative"},
#         "y": {"field": "tpr", "type": "quantitative"},
#         "color": {"field": "class", "type": "nominal"}
#       },
#       "layer": [
#         {"mark": "line"},
#         {
#           "selection": {
#             "label": {
#               "type": "single",
#               "nearest": true,
#               "on": "mouseover",
#               "encodings": ["x"],
#               "empty": "none"
#             }
#           },
#           "mark": "point",
#           "encoding": {
#             "opacity": {
#               "condition": {"selection": "label", "value": 1},
#               "value": 0
#             }
#           }
#         }
#       ]
#     },
#     {
#       "transform": [{"filter": {"selection": "label"}}],
#       "layer": [
#         {
#           "mark": {"type": "rule", "color": "gray"},
#           "encoding": {
#             "x": {"type": "quantitative", "field": "train_size"}
#           }
#         },
#         {
#           "encoding": {
#             "text": {"type": "quantitative", "field": "score"},
#             "x": {"type": "quantitative", "field": "train_size"},
#             "y": {"type": "quantitative", "field": "score"}
#           },
#           "layer": [
#             {
#               "mark": {
#                 "type": "text",
#                 "stroke": "white",
#                 "strokeWidth": 2,
#                 "align": "left",
#                 "dx": 5,
#                 "dy": -5
#               }
#             },
#             {
#               "mark": {"type": "text", "align": "left", "dx": 5, "dy": -5},
#               "encoding": {
#                 "color": {
#                   "type": "nominal", "field": "dataset", "scale": {
#                   "range": ["#3498DB", "#AB47BC"]
#                   },
#                   "legend": {
#                   "title": " "
#                   }
#                 }
#               }
#             }
#           ]
#         }
#       ]
#     }
#   ]
# }

def confusion_matrix(y_true, y_pred, labels=None, true_labels=None,
                          pred_labels=None, title=None, normalize=False,
                          hide_zeros=False, hide_counts=False):
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    cm = metrics.confusion_matrix(y_true, y_pred, labels=labels)
    if labels is None:
        classes = unique_labels(y_true, y_pred)
    else:
        classes = np.asarray(labels)

    if normalize:
        cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
        cm = np.around(cm, decimals=2)
        cm[np.isnan(cm)] = 0.0

    if true_labels is None:
        true_classes = classes
    else:
        validate_labels(classes, true_labels, "true_labels")

        true_label_indexes = np.in1d(classes, true_labels)

        true_classes = classes[true_label_indexes]
        cm = cm[true_label_indexes]

    if pred_labels is None:
        pred_classes = classes
    else:
        validate_labels(classes, pred_labels, "pred_labels")

        pred_label_indexes = np.in1d(classes, pred_labels)

        pred_classes = classes[pred_label_indexes]
        cm = cm[:, pred_label_indexes]

    def confusion_matrix_table(cm, pred_classes, true_classes):
        data=[]

        for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
            data.append([pred_classes[i], true_classes[j], cm[i,j]])
        return wandb.Table(
            columns=['Predicted', 'Actual', 'Count'],
            data=data
        )

    return confusion_matrix_table(cm, pred_classes, true_classes)

def plot_confusion_matrix(y_true, y_pred, labels=None, true_labels=None,
                          pred_labels=None, title=None, normalize=False,
                          hide_zeros=False, hide_counts=False):
    wandb.log({'confusion matrix': confusion_matrix(y_true, y_pred, labels, true_labels,
                          pred_labels, title, normalize,
                          hide_zeros, hide_counts)})


# {
#   "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
#   "padding": 5,
#   "width": 500,
#   "height": 500,
#   "data":
#     {
#       "name": "${history-table:rows:x-axis,key}"
#     },
#   "title": {
#     "text": "Confusion Matrix"
#   },
#     "mark": "circle",
#   "encoding": {
#     "x": {
#       "field": "Predicted",
#       "type": "nominal",
#       "axis": {
#         "maxExtent": 50,
#         "labelLimit": 40,
#         "labelAngle": -45
#       }
#     },
#     "y": {
#       "field": "Actual",
#       "type": "nominal"

#     },
#     "size": {
#       "field": "Count",
#       "type": "quantitative"
#     }
#   }
# }

def precision_recall(y_true, y_probas,
                          plot_micro=True,
                          classes_to_plot=None):
    y_true = np.array(y_true)
    y_probas = np.array(y_probas)

    classes = np.unique(y_true)
    probas = y_probas

    if classes_to_plot is None:
        classes_to_plot = classes

    binarized_y_true = label_binarize(y_true, classes=classes)
    if len(classes) == 2:
        binarized_y_true = np.hstack(
            (1 - binarized_y_true, binarized_y_true))

    pr_curves = {}
    indices_to_plot = np.in1d(classes, classes_to_plot)
    for i, to_plot in enumerate(indices_to_plot):
        if to_plot:
            average_precision = average_precision_score(
                binarized_y_true[:, i],
                probas[:, i])
            precision, recall, _ = precision_recall_curve(
                y_true, probas[:, i], pos_label=classes[i])

            samples = 20
            sample_precision = []
            sample_recall = []
            for k in range(samples):
                sample_precision.append(precision[int(len(precision)*k/samples)])
                sample_recall.append(recall[int(len(recall)*k/samples)])

            pr_curves[classes[i]] = (sample_precision, sample_recall)





    # if plot_micro:
    #     precision, recall, _ = precision_recall_curve(
    #         binarized_y_true.ravel(), probas.ravel())
    #     average_precision = average_precision_score(binarized_y_true,
    #                                                 probas,
    #                                                 average='micro')
    #     ax.plot(recall, precision,
    #             label='micro-average Precision-recall curve '
    #                   '(area = {0:0.3f})'.format(average_precision),
    #             color='navy', linestyle=':', linewidth=4)

    def pr_table(pr_curves):
        data=[]

        for i, class_name in enumerate(pr_curves.keys()):
            precision, recall = pr_curves[class_name]
            for p, r in zip(precision, recall):
                data.append([class_name, p, r])
        return wandb.Table(
            columns=['class', 'precision', 'recall'],
            data=data
        )


    return pr_table(pr_curves)

def plot_precision_recall(y_true, y_probas,
                          plot_micro=True,
                          classes_to_plot=None):
  wandb.log({'pr':precision_recall(y_true, y_probas,
                          plot_micro,
                          classes_to_plot)})
# { "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
#   "padding": 5,
#   "width": 500,
#   "height": 500,
#   "data":
#     {
#       "name": "${history-table:rows:x-axis,key}"
#     },
#   "title": {
#     "text": "Precision Recall"
#   },"layer": [
#     {
#       "encoding": {
#         "x": {"field": "precision", "type": "quantitative"},
#         "y": {"field": "recall", "type": "quantitative"},
#         "color": {"field": "class", "type": "nominal"}
#       },
#       "layer": [
#         {"mark": "line"},
#         {
#           "selection": {
#             "label": {
#               "type": "single",
#               "nearest": true,
#               "on": "mouseover",
#               "encodings": ["x"],
#               "empty": "none"
#             }
#           },
#           "mark": "point",
#           "encoding": {
#             "opacity": {
#               "condition": {"selection": "label", "value": 1},
#               "value": 0
#             }
#           }
#         }
#       ]
#     },
#     {
#       "transform": [{"filter": {"selection": "label"}}],
#       "layer": [
#         {
#           "encoding": {
#             "text": {"type": "quantitative", "field": "class"},
#             "x": {"type": "quantitative", "field": "precision"},
#             "y": {"type": "quantitative", "field": "recall"}
#           },
#           "layer": [
#             {
#               "mark": {
#                 "type": "text",
#                 "stroke": "white",
#                 "strokeWidth": 2,
#                 "align": "left",
#                 "dx": 5,
#                 "dy": -5
#               }
#             },
#             {
#               "mark": {"type": "text", "align": "left", "dx": 5, "dy": -5},
#               "encoding": {
#                 "color": {
#                   "type": "nominal", "field": "dataset", "scale": {
#                   "range": ["#3498DB", "#AB47BC", "#55BBBB", "#BB9955"]
#                   },
#                   "legend": {
#                   "title": " "
#                   }
#                 }
#               }
#             }
#           ]
#         }
#       ]
#     }
#   ]
# }


def plot_silhouette(X, cluster_labels, title='Silhouette Analysis',
                    metric='euclidean', copy=True, ax=None, figsize=None,
                    cmap='nipy_spectral', title_fontsize="large",
                    text_fontsize="medium"):
    cluster_labels = np.asarray(cluster_labels)

    le = LabelEncoder()
    cluster_labels_encoded = le.fit_transform(cluster_labels)

    n_clusters = len(np.unique(cluster_labels))

    silhouette_avg = silhouette_score(X, cluster_labels, metric=metric)

    sample_silhouette_values = silhouette_samples(X, cluster_labels,
                                                  metric=metric)

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    ax.set_title(title, fontsize=title_fontsize)
    ax.set_xlim([-0.1, 1])

    ax.set_ylim([0, len(X) + (n_clusters + 1) * 10 + 10])

    ax.set_xlabel('Silhouette coefficient values', fontsize=text_fontsize)
    ax.set_ylabel('Cluster label', fontsize=text_fontsize)

    y_lower = 10

    for i in range(n_clusters):
        ith_cluster_silhouette_values = sample_silhouette_values[
            cluster_labels_encoded == i]

        ith_cluster_silhouette_values.sort()

        size_cluster_i = ith_cluster_silhouette_values.shape[0]
        y_upper = y_lower + size_cluster_i

        color = plt.cm.get_cmap(cmap)(float(i) / n_clusters)

        ax.fill_betweenx(np.arange(y_lower, y_upper),
                         0, ith_cluster_silhouette_values,
                         facecolor=color, edgecolor=color, alpha=0.7)

        ax.text(-0.05, y_lower + 0.5 * size_cluster_i, str(le.classes_[i]),
                fontsize=text_fontsize)

        y_lower = y_upper + 10

    ax.axvline(x=silhouette_avg, color="red", linestyle="--",
               label='Silhouette score: {0:0.3f}'.format(silhouette_avg))

    ax.set_yticks([])  # Clear the y-axis labels / ticks
    ax.set_xticks(np.arange(-0.1, 1.0, 0.2))

    ax.tick_params(labelsize=text_fontsize)
    ax.legend(loc='best', fontsize=text_fontsize)

    return ax

def plot_feature_importances(clf, title='Feature Importance',
                             feature_names=None, max_num_features=20,
                             order='descending', x_tick_rotation=0, ax=None,
                             figsize=None, title_fontsize="large",
                             text_fontsize="medium"):
    if not hasattr(clf, 'feature_importances_'):
        raise TypeError('"feature_importances_" attribute not in classifier. '
                        'Cannot plot feature importances.')

    importances = clf.feature_importances_

    if hasattr(clf, 'estimators_')\
            and isinstance(clf.estimators_, list)\
            and hasattr(clf.estimators_[0], 'feature_importances_'):
        std = np.std([tree.feature_importances_ for tree in clf.estimators_],
                     axis=0)

    else:
        std = None

    if order == 'descending':
        indices = np.argsort(importances)[::-1]

    elif order == 'ascending':
        indices = np.argsort(importances)

    elif order is None:
        indices = np.array(range(len(importances)))

    else:
        raise ValueError('Invalid argument {} for "order"'.format(order))

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    if feature_names is None:
        feature_names = indices
    else:
        feature_names = np.array(feature_names)[indices]

    max_num_features = min(max_num_features, len(importances))

    ax.set_title(title, fontsize=title_fontsize)

    if std is not None:
        ax.bar(range(max_num_features),
               importances[indices][:max_num_features], color='r',
               yerr=std[indices][:max_num_features], align='center')
    else:
        ax.bar(range(max_num_features),
               importances[indices][:max_num_features],
               color='r', align='center')

    ax.set_xticks(range(max_num_features))
    ax.set_xticklabels(feature_names[:max_num_features],
                       rotation=x_tick_rotation)
    ax.set_xlim([-1, max_num_features])
    ax.tick_params(labelsize=text_fontsize)
    return ax

def plot_elbow_curve(clf, X, title='Elbow Plot', cluster_ranges=None, n_jobs=1,
                     show_cluster_time=True, ax=None, figsize=None,
                     title_fontsize="large", text_fontsize="medium"):
    if cluster_ranges is None:
        cluster_ranges = range(1, 12, 2)
    else:
        cluster_ranges = sorted(cluster_ranges)

    if not hasattr(clf, 'n_clusters'):
        raise TypeError('"n_clusters" attribute not in classifier. '
                        'Cannot plot elbow method.')

    tuples = Parallel(n_jobs=n_jobs)(delayed(_clone_and_score_clusterer)
                                     (clf, X, i) for i in cluster_ranges)
    clfs, times = zip(*tuples)

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    ax.set_title(title, fontsize=title_fontsize)
    ax.plot(cluster_ranges, np.absolute(clfs), 'b*-')
    ax.grid(True)
    ax.set_xlabel('Number of clusters', fontsize=text_fontsize)
    ax.set_ylabel('Sum of Squared Errors', fontsize=text_fontsize)
    ax.tick_params(labelsize=text_fontsize)

    if show_cluster_time:
        ax2_color = 'green'
        ax2 = ax.twinx()
        ax2.plot(cluster_ranges, times, ':', alpha=0.75, color=ax2_color)
        ax2.set_ylabel('Clustering duration (seconds)',
                       color=ax2_color, alpha=0.75,
                       fontsize=text_fontsize)
        ax2.tick_params(colors=ax2_color, labelsize=text_fontsize)

    return ax


def _clone_and_score_clusterer(clf, X, n_clusters):
    start = time.time()
    clf = clone(clf)
    setattr(clf, 'n_clusters', n_clusters)
    return clf.fit(X).score(X), time.time() - start

## -------------- YB Plots Start Here ------------
def plot_class_balance(y_train, y_test=None):
    # Get the unique values from the dataset
    y_train = np.array(y_train)
    y_test = np.array(y_test)
    targets = (y_train,) if y_test is None else (y_train, y_test)
    classes_ = np.array(unique_labels(*targets))

    # Compute the class counts
    class_counts_train = np.array([(y_train == c).sum() for c in classes_])
    class_counts_test = np.array([(y_test == c).sum() for c in classes_])

    def class_balance(classes_, class_counts_train, class_counts_test):
        class_dict = []
        dataset_dict = []
        count_dict = []
        for i in range(len(classes_)):
            # add class counts from training set
            class_dict.append(classes_[i])
            dataset_dict.append("train")
            count_dict.append(class_counts_train[i])
            # add class counts from test set
            class_dict.append(classes_[i])
            dataset_dict.append("test")
            count_dict.append(class_counts_test[i])

        return wandb.Table(
            columns=['class', 'dataset', 'count'],
            data=[
                [class_dict[i], dataset_dict[i], count_dict[i]] for i in range(len(class_dict))
            ]
        )
    wandb.log({'class_balance': class_balance(classes_, class_counts_train, class_counts_test)})
    '''
    {
      "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
      "width": 500,
      "height": 500,
      "title": "Class Proportions in Target Variable",
      "data": {
        "name": "${history-table:rows:x-axis,key}"
      },
      "selection": {
        "highlight": {"type": "single", "empty": "none", "on": "mouseover"},
        "select": {"type": "multi"}
      },
      "mark": {
        "type": "bar",
        "stroke": "black",
        "cursor": "pointer"
      },
      "encoding": {
        "x": {"field": "class", "type": "ordinal"},
        "y": {"field": "count", "type": "quantitative", "axis": {"title": "Number of instances"}},
        "fillOpacity": {
          "condition": {"selection": "select", "value": 1},
          "value": 0.3
        },
        "color": {
          "field": "dataset",
          "type": "nominal",
          "scale": {
            "domain": ["train", "test"],
            "range": ["#3498DB", "#4DB6AC"]
          },
          "legend": {"title": "Dataset"}
        },
        "strokeWidth": {
          "condition": [
            {
              "test": {
                "and": [
                  {"selection": "select"},
                  "length(data(\"select_store\"))"
                ]
              },
              "value": 2
            },
            {"selection": "highlight", "value": 1}
          ],
          "value": 0
        }
      },
      "config": {
        "scale": {
          "bandPaddingInner": 0.2
        }
      }
    }
    '''

def plot_calibration_curve(X, y, estimator, name):
    """Plot calibration curve for estimator w/o and with calibration. """
    # Create dataset of classification task with many redundant and few
    # informative features
    X, y = datasets.make_classification(n_samples=100000, n_features=20,
                                        n_informative=2, n_redundant=10,
                                        random_state=42)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.99,
                                                        random_state=42)
    # Calibrated with isotonic calibration
    isotonic = CalibratedClassifierCV(estimator, cv=2, method='isotonic')

    # Calibrated with sigmoid calibration
    sigmoid = CalibratedClassifierCV(estimator, cv=2, method='sigmoid')

    # Logistic regression with no calibration as baseline
    lr = LogisticRegression(C=1.)

    model_dict = [] # color
    frac_positives_dict = [] # y axis
    mean_pred_value_dict = [] # x axis
    hist_dict = [] # barchart y
    edge_dict = [] # barchart x

    # Add curve for perfectly calibrated model
    # format: model, fraction_of_positives, mean_predicted_value
    model_dict.append('Perfectly calibrated')
    frac_positives_dict.append(0)
    mean_pred_value_dict.append(0)
    hist_dict.append(0)
    edge_dict.append(0)
    model_dict.append('Perfectly calibrated')
    hist_dict.append(0)
    edge_dict.append(0)
    frac_positives_dict.append(1)
    mean_pred_value_dict.append(1)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.98,
                                                        random_state=42)

    # Add curve for LogisticRegression baseline and other models
    for clf, name in [(lr, 'Logistic'),
                      (estimator, name),
                      (isotonic, name + ' + Isotonic'),
                      (sigmoid, name + ' + Sigmoid')]:
        clf.fit(X_train, y_train)
        y_pred = clf.predict(X_test)
        if hasattr(clf, "predict_proba"):
            prob_pos = clf.predict_proba(X_test)[:, 1]
        else:  # use decision function
            prob_pos = clf.decision_function(X_test)
            prob_pos = \
                (prob_pos - prob_pos.min()) / (prob_pos.max() - prob_pos.min())

        clf_score = brier_score_loss(y_test, prob_pos, pos_label=y.max())

        fraction_of_positives, mean_predicted_value = \
            calibration_curve(y_test, prob_pos, n_bins=10)
        hist, edges = np.histogram(
                        prob_pos,
                        bins=10,
                        density=False)

        # format: model, fraction_of_positives, mean_predicted_value
        for i in range(len(fraction_of_positives)):
            hist_dict.append(hist[i])
            edge_dict.append(edges[i])
            model_dict.append(name)
            frac_positives_dict.append(round_3(fraction_of_positives[i]))
            mean_pred_value_dict.append(round_3(mean_predicted_value[i]))

        def calibration_curves(model_dict, frac_positives_dict, mean_pred_value_dict, hist_dict, edge_dict):
            return wandb.Table(
                columns=['model', 'fraction_of_positives', 'mean_predicted_value', 'hist_dict', 'edge_dict'],
                data=[
                    [model_dict[i], frac_positives_dict[i], mean_pred_value_dict[i], hist_dict[i], edge_dict[i]] for i in range(len(model_dict))
                ]
            )
    wandb.log({'calibration_curve': calibration_curves(model_dict, frac_positives_dict, mean_pred_value_dict, hist_dict, edge_dict)})
    '''
    {
      "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
      "padding": 5,
      "data":
        {
          "name": "${history-table:rows:x-axis,key}"
        },
      "title": "Calibration Curve",
      "vconcat": [
        {
          "layer": [
          {
            "encoding": {
              "x": {"field": "mean_predicted_value", "type": "quantitative", "axis": {"title": "Mean predicted value"}},
              "y": {"field": "fraction_of_positives", "type": "quantitative", "axis": {"title": "Fraction of positives"}},
              "color": {
                "field": "model",
                "type": "nominal",
                "axis": {"title": "Models"},
                "scale": {
                  "range": ["#3498DB", "#AB47BC", "#55BBBB", "#BB9955"]
                }
              }
            },
            "layer": [
              {
                "mark": {
                  "type": "line",
                  "point": {
                    "filled": false,
                    "fill": "white"
                  }
                }
              }
            ]
          }]
        },
        {
        "mark": {"type": "tick"},
        "encoding": {
          "x": {"field": "edge_dict", "type": "quantitative","bin":true, "axis": {"title": "Mean predicted value"}},
          "y": {"field": "hist_dict", "type": "quantitative", "axis": {"title": "Counts"}},
          "strokeWidth": {
            "value": 2
          },
          "color": {
            "field": "model",
            "type": "nominal",
            "axis": {"title": "Models"},
            "scale": {
              "range": ["#3498DB", "#AB47BC", "#55BBBB", "#BB9955"]
            }
          }
        }
        }
      ]
    }
    '''

def plot_outlier_candidates(reg, X, y):
    # Fit a linear model to X and y to compute MSE
    reg.fit(X, y)

    # Leverage is computed as the diagonal of the projection matrix of X
    leverage = (X * np.linalg.pinv(X).T).sum(1)

    # Compute the rank and the degrees of freedom of the OLS model
    rank = np.linalg.matrix_rank(X)
    df = X.shape[0] - rank

    # Compute the MSE from the residuals
    residuals = y - reg.predict(X)
    mse = np.dot(residuals, residuals) / df

    # Compute Cook's distance
    residuals_studentized = residuals / np.sqrt(mse) / np.sqrt(1 - leverage)
    distance_ = residuals_studentized ** 2 / X.shape[1]
    distance_ *= leverage / (1 - leverage)

    # Compute the p-values of Cook's Distance
    p_values_ = sp.stats.f.sf(distance_, X.shape[1], df)

    # Compute the influence threshold rule of thumb
    influence_threshold_ = 4 / X.shape[0]
    outlier_percentage_ = (
        sum(distance_ > influence_threshold_) / X.shape[0]
    )
    outlier_percentage_ *= 100.0

    # Draw a stem plot with the influence for each instance
    # format: distance_, len(distance_), influence_threshold_, round_3(outlier_percentage_)
    def outlier_candidates(distance, outlier_percentage, influence_threshold):
        return wandb.Table(
            columns=['distance', 'instance_indicies', 'outlier_percentage', 'influence_threshold'],
            data=[
                [distance[i], i, round_3(outlier_percentage_), influence_threshold_] for i in range(len(distance))
            ]
        )
    wandb.log({'outlier_candidates': outlier_candidates(distance_, outlier_percentage_, influence_threshold_)})
    return
    '''
    {
      "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
      "padding": 5,
      "data":
        {
          "name": "${history-table:rows:x-axis,key}"
        },
      "title": {
        "text": "Cook's Distance Outlier Detection"
      },
     "layer": [{
        "mark": "bar",
        "encoding": {
          "x": {
            "field": "instance_indicies",
            "type": "quantitative",
            "axis": {"title": "Instances"}
          },
          "y": {
            "field": "distance",
            "type": "quantitative",
            "axis": {"title": "Influence (Cook's Distance)"}
          },
          "color":  {"value": "#3498DB"},
          "opacity":  {"value": 0.4}
        }
      },{
        "mark": {
          "type":"rule",
          "strokeDash": [6, 4],
          "stroke":"#f88c99"},
        "encoding": {
          "y": {
            "field": "influence_threshold",
            "type": "quantitative"
          },
          "color": {"value": "red"},
          "size": {"value": 1}
        }
      }, {
        "mark": {
          "type": "text",
          "align": "left",
          "baseline": "top",
          "dx": 0
        }
      }]
    }
    '''

def plot_residuals(model, X, y):
    # Create the train and test splits
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

    # Store labels and colors for the legend ordered by call
    _labels, _colors = [], []
    model.fit(X_train, y_train)
    train_score_ = model.score(X_train, y_train)
    test_score_ = model.score(X_test, y_test)

    y_pred_train = model.predict(X_train)
    residuals_train = y_pred_train - y_train

    y_pred_test = model.predict(X_test)
    residuals_test = y_pred_test - y_test

    # format:
    # Legend: train_score_, test_score_ (play with opacity)
    # Scatterplot: dataset(train, test)(color), y_pred(x), residuals(y)
    # Histogram: dataset(train, test)(color), residuals(y), aggregate(residuals(x)) with bins=50
    def residuals(y_pred_train, residuals_train, y_pred_test, residuals_test, train_score_, test_score_):
        y_pred_dict = []
        dataset_dict = []
        residuals_dict = []
        for i in range(280):
            # add class counts from training set
            y_pred_dict.append(y_pred_train[i])
            dataset_dict.append("train")
            residuals_dict.append(residuals_train[i])
        for i in range(20):
            # add class counts from test set
            y_pred_dict.append(y_pred_test[i])
            dataset_dict.append("test")
            residuals_dict.append(residuals_test[i])

        return wandb.Table(
            columns=['dataset', 'y_pred', 'residuals', 'train_score', 'test_score'],
            data=[
                [dataset_dict[i], y_pred_dict[i], residuals_dict[i], train_score_, test_score_] for i in range(len(y_pred_dict))
            ]
        )
    wandb.log({'residuals': residuals(y_pred_train, residuals_train, y_pred_test, residuals_test, train_score_, test_score_)})
    '''
    {
      "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
      "width": "container",
      "data":
        {
          "name": "${history-table:rows:x-axis,key}"
        },
      "title": "Residuals Plot",
      "vconcat": [
        {
          "layer": [
          {
            "encoding": {
              "y": {"field": "y_pred", "type": "quantitative", "axis": {"title": "Predicted Value"}},
              "x": {"field": "residuals", "type": "quantitative", "axis": {"title": "Residuals"}},
              "color": {
                "field": "dataset",
                "type": "nominal",
                "axis": {"title": "Dataset"}
              }
            },
            "layer": [
              {
                "mark": {
                  "type": "point",
                  "opacity": 0.5,
                  "filled" : true
                }
              }
            ]
          }]
        },
        {
        "mark": {"type": "bar",
                "opacity": 0.8},
        "encoding": {
          "x": {"field": "residuals", "type": "quantitative", "bin": true, "axis": {"title": "Residuals"}},
          "y": {
            "aggregate": "count", "field": "residuals", "type": "quantitative", "axis": {"title": "Distribution"}},
          "strokeWidth": {
            "value": 1
          },
          "color": {
            "field": "dataset",
            "type": "nominal",
            "axis": {"title": "Dataset"},
            "scale": {
              "range": ["#AB47BC", "#3498DB"]
            }
          }
        }
        }
      ]
    }
    '''
