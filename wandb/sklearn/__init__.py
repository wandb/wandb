from __future__ import absolute_import, division, print_function, unicode_literals
import wandb
import time
import itertools
import sklearn
import numpy as np
import scipy as sp
from wandb.sklearn.utils import *
from sklearn.base import clone
from joblib import Parallel, delayed
from sklearn import model_selection
from sklearn import datasets
from sklearn import metrics
from sklearn.metrics import roc_curve, auc, precision_recall_curve, average_precision_score
from sklearn.metrics import (brier_score_loss, precision_score, recall_score, f1_score)
from sklearn.metrics import silhouette_score, silhouette_samples
from sklearn.preprocessing import label_binarize
from sklearn.preprocessing import LabelEncoder
from sklearn.calibration import calibration_curve
from sklearn import naive_bayes
from sklearn.utils.multiclass import unique_labels, type_of_target
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.linear_model import LogisticRegression
from warnings import simplefilter
# ignore all future warnings
simplefilter(action='ignore', category=FutureWarning)

from wandb.plots.roc import roc
from wandb.plots.precision_recall import precision_recall

def round_3(n):
    return round(n, 3)
def round_2(n):
    return round(n, 2)
chart_limit = 1000
def get_named_labels(labels, numeric_labels):
        return np.array([labels[num_label] for num_label in numeric_labels])


def plot_classifier(model, X_train, X_test,
                    y_train, y_test, y_pred, y_probas,
                    labels, is_binary=False, model_name='Classifier',
                    feature_names=None):
    """
    Generates all sklearn classifier plots supported by W&B.
        The following plots are generated:
        feature importances, learning curve, confusion matrix, summary metrics,
        class balance plot, calibration curve, roc curve & precision recall curve.

    Should only be called with a fitted classifer (otherwise an error is thrown).

    Arguments:
        model (classifier): Takes in a fitted classifier.
        X_train (arr): Training set features.
        y_train (arr): Training set labels.
        X_test (arr): Test set features.
        y_test (arr): Test set labels.
        y_pred (arr): Test set predictions by the model passed.
        y_probas (arr): Test set predicted probabilities by the model passed.
        labels (list): Named labels for target varible (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example labels= ['dog', 'cat', 'owl'] all 0s are
                        replaced by 'dog', 1s by 'cat'.
        is_binary (bool): Is the model passed a binary classifier? Defaults to False
        model_name (str): Model name. Defaults to 'Classifier'
        feature_names (list): Names for features. Makes plots easier to read by
                                replacing feature indexes with corresponding names.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
            under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_classifier(model, X_train, X_test, y_train, y_test,
                        y_pred, y_probas, ['cat', 'dog'], False,
                        'RandomForest', ['barks', 'drools, 'plays_fetch', 'breed'])
    """
    wandb.termlog('\nPlotting %s.'%model_name)
    plot_feature_importances(model, feature_names)
    wandb.termlog('Logged feature importances.')
    plot_learning_curve(model, X_train, y_train)
    wandb.termlog('Logged learning curve.')
    plot_confusion_matrix(y_test, y_pred, labels)
    wandb.termlog('Logged confusion matrix.')
    plot_summary_metrics(model, X=X_train, y=y_train, X_test=X_test, y_test=y_test)
    wandb.termlog('Logged summary metrics.')
    plot_class_proportions(y_train, y_test, labels)
    wandb.termlog('Logged class proportions.')
    if(not isinstance(model, naive_bayes.MultinomialNB)):
        plot_calibration_curve(model, X_train, y_train, model_name)
    wandb.termlog('Logged calibration curve.')
    plot_roc(y_test, y_probas, labels)
    wandb.termlog('Logged roc curve.')
    plot_precision_recall(y_test, y_probas, labels)
    wandb.termlog('Logged precision recall curve.')
    # if is_binary:
        # plot_decision_boundaries(model, X_train, y_train)
        # wandb.termlog('Logged decision boundary plot.')


def plot_regressor(model, X_train, X_test, y_train, y_test,  model_name='Regressor'):
    """
    Generates all sklearn regressor plots supported by W&B.
        The following plots are generated:
        learning curve, summary metrics, residuals plot, outlier candidates.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Arguments:
        model (regressor): Takes in a fitted regressor.
        X_train (arr): Training set features.
        y_train (arr): Training set labels.
        X_test (arr): Test set features.
        y_test (arr): Test set labels.
        model_name (str): Model name. Defaults to 'Regressor'

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
            under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_regressor(reg, X_train, X_test, y_train, y_test, 'Ridge')
    """
    wandb.termlog('\nPlotting %s.'%model_name)
    plot_summary_metrics(model, X_train, y_train, X_test, y_test)
    wandb.termlog('Logged summary metrics.')
    plot_learning_curve(model, X_train, y_train)
    wandb.termlog('Logged learning curve.')
    plot_outlier_candidates(model, X_train, y_train)
    wandb.termlog('Logged outlier candidates.')
    plot_residuals(model, X_train, y_train)
    wandb.termlog('Logged residuals.')


def plot_clusterer(model, X_train, cluster_labels, labels=None, model_name='Clusterer'):
    """
    Generates all sklearn clusterer plots supported by W&B.
        The following plots are generated:
        elbow curve, silhouette plot.

    Should only be called with a fitted clusterer (otherwise an error is thrown).

    Arguments:
        model (clusterer): Takes in a fitted clusterer.
        X_train (arr): Training set features.
        cluster_labels (list): Names for cluster labels. Makes plots easier to read
                            by replacing cluster indexes with corresponding names.
        labels (list): Named labels for target varible (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example labels= ['dog', 'cat', 'owl'] all 0s are
                        replaced by 'dog', 1s by 'cat'.
        model_name (str): Model name. Defaults to 'Clusterer'

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_clusterer(kmeans, X, cluster_labels, labels, 'KMeans')
    """
    wandb.termlog('\nPlotting %s.'%model_name)
    if isinstance(model, sklearn.cluster.KMeans):
        plot_elbow_curve(model, X_train)
        wandb.termlog('Logged elbow curve.')
        plot_silhouette(model, X_train, cluster_labels, labels=labels, kmeans=True)
    else:
        plot_silhouette(model, X_train, cluster_labels, kmeans=False)
    wandb.termlog('Logged silhouette plot.')


def summary_metrics(model=None, X=None, y=None, X_test=None, y_test=None):
    """
    Calculates summary metrics (like mse, mae, r2 score) for both regression and
    classification algorithms.

    Called by plot_summary_metrics to visualize metrics. Please use the function
    plot_summary_metric() if you wish to visualize your summary metrics.
    """
    if (test_missing(model=model, X=X, y=y, X_test=X_test, y_test=y_test) and
        test_types(model=model, X=X, y=y, X_test=X_test, y_test=y_test) and
        test_fitted(model)):
        y = np.asarray(y)
        y_test = np.asarray(y_test)
        metric_name=[]
        metric_value=[]
        model_name = model.__class__.__name__

        params = {}
        # Log model params to wandb.config
        for v in vars(model):
            if isinstance(getattr(model, v), str) \
                or isinstance(getattr(model, v), bool) \
                    or isinstance(getattr(model, v), int) \
                    or isinstance(getattr(model, v), float):
                params[v] = getattr(model, v)

        # Classifier Metrics
        if sklearn.base.is_classifier(model):
            y_pred = model.predict(X_test)
            y_probas = model.predict_proba(X_test)

            metric_name.append("accuracy_score")
            metric_value.append(round_2(sklearn.metrics.accuracy_score(y_test, y_pred)))
            metric_name.append("precision")
            metric_value.append(round_2(sklearn.metrics.precision_score(y_test, y_pred, average="weighted")))
            metric_name.append("recall")
            metric_value.append(round_2(sklearn.metrics.recall_score(y_test, y_pred, average="weighted")))
            metric_name.append("f1_score")
            metric_value.append(round_2(sklearn.metrics.f1_score(y_test, y_pred, average="weighted")))

        # Regression Metrics
        elif sklearn.base.is_regressor(model):
            y_pred = model.predict(X_test)

            metric_name.append("mae")
            metric_value.append(round_2(sklearn.metrics.mean_absolute_error(y_test, y_pred)))
            metric_name.append("mse")
            metric_value.append(round_2(sklearn.metrics.mean_squared_error(y_test, y_pred)))
            metric_name.append("r2_score")
            metric_value.append(round_2(sklearn.metrics.r2_score(y_test, y_pred)))

        return wandb.visualize(
            'wandb/metrics/v1', wandb.Table(
            columns=['metric_name', 'metric_value', 'model_name'],
            data= [
                [metric_name[i], metric_value[i], model_name] for i in range(len(metric_name))
            ]
        ))


def plot_summary_metrics(model=None, X=None, y=None, X_test=None, y_test=None):
    """
    Logs the charts generated by summary_metrics in wandb.

    Should only be called with a fitted model (otherwise an error is thrown).

    Arguments:
        model (clf or reg): Takes in a fitted regressor or classifier.
        X (arr): Training set features.
        y (arr): Training set labels.
        X_test (arr): Test set features.
        y_test (arr): Test set labels.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_summary_metrics(model, X_train, X_test, y_train, y_test)
    """
    wandb.log({'summary_metrics': summary_metrics(model, X, y, X_test, y_test)})



def learning_curve(model, X, y, cv=None,
                    shuffle=False, random_state=None,
                    train_sizes=None, n_jobs=1, scoring=None):
    """
    Trains model on datasets of varying lengths and generates a plot of
    scores vs training sizes for both training and test sets.

    Called by plot_learning_curve to visualize learning curve. Please use the function
    plot_learning_curve() if you wish to visualize your learning curves.

    """
    if train_sizes is None:
        train_sizes = np.linspace(.1, 1.0, 5)
    if (test_missing(model=model, X=X, y=y) and
        test_types(model=model, X=X, y=y)):
        y = np.asarray(y)
        train_sizes, train_scores, test_scores = model_selection.learning_curve(
            model, X, y, cv=cv, n_jobs=n_jobs, train_sizes=train_sizes,
            scoring=scoring, shuffle=shuffle, random_state=random_state)
        train_scores_mean = np.mean(train_scores, axis=1)
        train_scores_std = np.std(train_scores, axis=1)
        test_scores_mean = np.mean(test_scores, axis=1)
        test_scores_std = np.std(test_scores, axis=1)

        def learning_curve_table(train, test, trainsize):
            data=[]
            for i in range(len(train)):
                if i >= chart_limit/2:
                    wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                    break
                train_set = ["train", round(train[i],2), trainsize[i]]
                test_set = ["test", round(test[i],2), trainsize[i]]
                data.append(train_set)
                data.append(test_set)
            return wandb.visualize(
                'wandb/learning_curve/v1', wandb.Table(
                columns=['dataset', 'score', 'train_size'],
                data=data
            ))

        return learning_curve_table(train_scores_mean, test_scores_mean, train_sizes)


def plot_learning_curve(model=None, X=None, y=None, cv=None,
                        shuffle=False, random_state=None,
                        train_sizes=None, n_jobs=1, scoring=None):
    """
    Logs the plots generated by learning_curve() to wandb.
    Please note this function fits the model to datasets of varying sizes when called.

    Arguments:
        model (clf or reg): Takes in a fitted regressor or classifier.
        X (arr): Dataset features.
        y (arr): Dataset labels.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_learning_curve(model, X, y)
    """
    wandb.log({'learning_curve': learning_curve(model, X, y, cv, shuffle,
        random_state, train_sizes, n_jobs, scoring)})


def plot_roc(y_true=None, y_probas=None, labels=None,
             plot_micro=True, plot_macro=True, classes_to_plot=None):
     """
     Logs the plots generated by roc() to wandb.

     Arguments:
         y_true (arr): Test set labels.
         y_probas (arr): Test set predicted probabilities.
         labels (list): Named labels for target varible (y). Makes plots easier to
                         read by replacing target values with corresponding index.
                         For example labels= ['dog', 'cat', 'owl'] all 0s are
                         replaced by 'dog', 1s by 'cat'.

     Returns:
         Nothing. To see plots, go to your W&B run page then expand the 'media' tab
               under 'auto visualizations'.

     Example:
         wandb.sklearn.plot_roc(y_true, y_probas, labels)
     """
     wandb.log({'roc': roc(y_true, y_probas, labels, plot_micro, plot_macro, classes_to_plot)})



def confusion_matrix(y_true=None, y_pred=None, labels=None, true_labels=None,
                          pred_labels=None, title=None, normalize=False,
                          hide_zeros=False, hide_counts=False):
    """
    Computes the confusion matrix to evaluate the accuracy of a classification.

    Called by plot_confusion_matrix to visualize roc curves. Please use the function
    plot_confusion_matrix() if you wish to visualize your confusion matrix.
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    if (test_missing(y_true=y_true, y_pred=y_pred) and
        test_types(y_true=y_true, y_pred=y_pred)):
        cm = metrics.confusion_matrix(y_true, y_pred)
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
            count = 0
            for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
                if labels is not None and (isinstance(pred_classes[i], int)
                                    or isinstance(pred_classes[0], np.integer)):
                    pred_dict = labels[pred_classes[i]]
                    true_dict = labels[true_classes[j]]
                else:
                    pred_dict = pred_classes[i]
                    true_dict = true_classes[j]
                data.append([pred_dict, true_dict, cm[i,j]])
                count+=1
                if count >= chart_limit:
                    wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                    break
            return wandb.visualize(
                'wandb/confusion_matrix/v1', wandb.Table(
                columns=['Predicted', 'Actual', 'Count'],
                data=data
            ))

        return confusion_matrix_table(cm, pred_classes, true_classes)


def plot_confusion_matrix(y_true=None, y_pred=None, labels=None, true_labels=None,
                          pred_labels=None, title=None, normalize=False,
                          hide_zeros=False, hide_counts=False):
    """
    Logs the plots generated by confusion_matrix() to wandb.

    Arguments:
        y_true (arr): Test set labels.
        y_probas (arr): Test set predicted probabilities.
        labels (list): Named labels for target varible (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example labels= ['dog', 'cat', 'owl'] all 0s are
                        replaced by 'dog', 1s by 'cat'.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_confusion_matrix(y_true, y_probas, labels)
    """
    wandb.log({'confusion_matrix': confusion_matrix(y_true, y_pred, labels, true_labels,
                          pred_labels, title, normalize,
                          hide_zeros, hide_counts)})


def plot_precision_recall(y_true=None, y_probas=None, labels=None,
                          plot_micro=True, classes_to_plot=None):
    """
    Logs the plots generated by precision_recall() to wandb.

    Arguments:
        y_true (arr): Test set labels.
        y_probas (arr): Test set predicted probabilities.
        labels (list): Named labels for target varible (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example labels= ['dog', 'cat', 'owl'] all 0s are
                        replaced by 'dog', 1s by 'cat'.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_precision_recall(y_true, y_probas, labels)
    """
    wandb.log({'precision_recall':precision_recall(y_true, y_probas,
                          labels, plot_micro, classes_to_plot)})


def plot_feature_importances(model=None, feature_names=None,
                            title='Feature Importance', max_num_features=50):
    """
    Evaluates & plots the importance of each feature for the classification task.

    Should only be called with a fitted classifer (otherwise an error is thrown).
    Only works with classifiers that have a feature_importances_ attribute, like trees.

    Arguments:
        model (clf): Takes in a fitted classifier.
        feature_names (list): Names for features. Makes plots easier to read by
                                replacing feature indexes with corresponding names.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_feature_importances(model, ['width', 'height, 'length'])
    """
    attributes_to_check = ['feature_importances_', 'coef_']
    def get_attributes_as_formatted_string():
        result = ''
        for index in range(len(attributes_to_check) - 1):
            if result == '':
                result = attributes_to_check[index]
            else:
                result = ", ".join([result, attributes_to_check[index]])

        return " or ".join([result, attributes_to_check[-1]])

    def check_for_attribute_on(model):
        for each in attributes_to_check:
            if hasattr(model, each):
                return each
        return None

    found_attribute = check_for_attribute_on(model)
    if found_attribute is None:
        wandb.termwarn("%s attribute not in classifier. Cannot plot feature importances." % get_attributes_as_formatted_string())
        return

    if (test_missing(model=model) and test_types(model=model) and
        test_fitted(model)):
        feature_names = np.asarray(feature_names)
        if found_attribute == 'feature_importances_':
            importances = model.feature_importances_
        if found_attribute == 'coef_':  # ElasticNet or ElasticNetCV like models
            importances = model.coef_

        indices = np.argsort(importances)[::-1]

        if feature_names is None:
            feature_names = indices
        else:
            feature_names = np.array(feature_names)[indices]

        max_num_features = min(max_num_features, len(importances))

        # Draw a stem plot with the influence for each instance
        # format:
        # x = feature_names[:max_num_features]
        # y = importances[indices][:max_num_features]
        def feature_importances_table(feature_names, importances):
            return wandb.visualize(
                'wandb/feature_importances/v1', wandb.Table(
                columns=['feature_names', 'importances'],
                data=[
                    [feature_names[i], importances[i]] for i in range(len(feature_names))
                ]
            ))
        wandb.log({'feature_importances': feature_importances_table(feature_names, importances)})
        return feature_importances_table(feature_names, importances)

def plot_elbow_curve(clusterer=None, X=None, cluster_ranges=None, n_jobs=1,
                    show_cluster_time=True):
    """
    Measures and plots the percentage of variance explained as a function of the
        number of clusters, along with training times. Useful in picking the
        optimal number of clusters.

    Should only be called with a fitted clusterer (otherwise an error is thrown).
    Please note this function fits the model on the training set when called.

    Arguments:
        model (clusterer): Takes in a fitted clusterer.
        X (arr): Training set features.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_elbow_curve(model, X_train)
    """
    if not hasattr(clusterer, 'n_clusters'):
        wandb.termlog('n_clusters attribute not in classifier. Cannot plot elbow method.')
        return
    if (test_missing(clusterer=clusterer) and test_types(clusterer=clusterer) and
        test_fitted(clusterer)):
        if cluster_ranges is None:
            cluster_ranges = range(1, 10, 2)
        else:
            cluster_ranges = sorted(cluster_ranges)

        if not hasattr(clusterer, 'n_clusters'):
            raise TypeError('"n_clusters" attribute not in classifier. '
                            'Cannot plot elbow method.')

        def _clone_and_score_clusterer(clusterer, X, n_clusters):
            start = time.time()
            clusterer = clone(clusterer)
            setattr(clusterer, 'n_clusters', n_clusters)
            return clusterer.fit(X).score(X), time.time() - start

        tuples = Parallel(n_jobs=n_jobs)(delayed(_clone_and_score_clusterer)
                                         (clusterer, X, i) for i in cluster_ranges)
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

        def elbow_curve(cluster_ranges, clfs, times):
            return wandb.visualize(
                'wandb/elbow/v1',
                wandb.Table(
                        columns=['cluster_ranges', 'errors', 'clustering_time'],
                        data=[
                            [cluster_ranges[i], clfs[i], times[i]] for i in range(len(cluster_ranges))
                        ]
            ))
        wandb.log({'elbow_curve': elbow_curve(cluster_ranges, clfs, times)})
        return


def plot_silhouette(clusterer=None, X=None, cluster_labels=None, labels=None,
                    metric='euclidean', kmeans=True):
    """
    Measures & plots a measure of how close each point in one cluster is to points
        in the neighboring clusters. Silhouette coefficients near +1 indicate that
        the sample is far away from the neighboring clusters. A value of 0 indicates
         that the sample is on or very close to the decision boundary between two
         neighboring clusters and negative values indicate that those samples might
         have been assigned to the wrong cluster.

    Should only be called with a fitted clusterer (otherwise an error is thrown).
    Please note this function fits the model on the training set when called.

    Arguments:
        model (clusterer): Takes in a fitted clusterer.
        X (arr): Training set features.
        cluster_labels (list): Names for cluster labels. Makes plots easier to read
                            by replacing cluster indexes with corresponding names.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_silhouette(model, X_train, ['spam', 'not spam'])
    """
    if (test_missing(clusterer=clusterer) and test_types(clusterer=clusterer) and
        test_fitted(clusterer)):
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
        cluster_labels_encoded = le.fit_transform(cluster_labels)
        n_clusters = len(np.unique(cluster_labels))

        # The silhouette_score gives the average value for all the samples.
        # This gives a perspective into the density and separation of the formed
        # clusters
        silhouette_avg = silhouette_score(X, cluster_labels, metric=metric)

        # Compute the silhouette scores for each sample
        sample_silhouette_values = silhouette_samples(X, cluster_labels,
                                                      metric=metric)

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
            ith_cluster_silhouette_values = \
                sample_silhouette_values[cluster_labels == i]

            ith_cluster_silhouette_values.sort()

            size_cluster_i = ith_cluster_silhouette_values.shape[0]
            y_upper = y_lower + size_cluster_i

            y_values = np.arange(y_lower, y_upper)

            for j in range(len(y_values)):
                y_sil.append(y_values[j])
                x_sil.append(ith_cluster_silhouette_values[j])
                color_sil.append(i)
                count+=1
                if count >= chart_limit:
                    wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                    break

            # Compute the new y_lower for next plot
            y_lower = y_upper + 10  # 10 for the 0 samples

        # Plot 2: Scatter Plot showing the actual clusters formed
        if kmeans:
            centers = clusterer.cluster_centers_
            def silhouette(x, y, colors, centerx, centery, y_sil, x_sil, color_sil, silhouette_avg):
                return wandb.visualize(
                    'wandb/silhouette_/v1', wandb.Table(
                    columns=['x', 'y', 'colors', 'centerx', 'centery', 'y_sil', 'x1', 'x2', 'color_sil', 'silhouette_avg'],
                    data=[
                        [x[i], y[i], colors[i], centerx[colors[i]], centery[colors[i]],
                        y_sil[i], 0, x_sil[i], color_sil[i], silhouette_avg]
                        for i in range(len(color_sil))
                    ]
                ))
            wandb_key = 'silhouette_plot'
            wandb.log({wandb_key: silhouette(X[:, 0], X[:, 1], cluster_labels, centers[:, 0], centers[:, 1], y_sil, x_sil, color_sil, silhouette_avg)})
        else:
            centerx = [None] * len(color_sil)
            centery = [None] * len(color_sil)
            def silhouette(x, y, colors, centerx, centery, y_sil, x_sil, color_sil, silhouette_avg):
                return wandb.visualize(
                    'wandb/silhouette_/v1', wandb.Table(
                    columns=['x', 'y', 'colors', 'centerx', 'centery', 'y_sil', 'x1', 'x2', 'color_sil', 'silhouette_avg'],
                    data=[
                        [x[i], y[i], colors[i], None, None,
                        y_sil[i], 0, x_sil[i], color_sil[i], silhouette_avg]
                        for i in range(len(color_sil))
                    ]
                ))
            wandb_key = 'silhouette_plot'
            wandb.log({wandb_key: silhouette(X[:, 0], X[:, 1], cluster_labels, centerx, centery, y_sil, x_sil, color_sil, silhouette_avg)})
        return


def plot_class_proportions(y_train=None, y_test=None, labels=None):
    """
    Plots the distribution of target classses in training and test sets.
        Useful for detecting imbalanced classes.

    Arguments:
        y_train (arr): Training set labels.
        y_test (arr): Test set labels.
        labels (list): Named labels for target varible (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example labels= ['dog', 'cat', 'owl'] all 0s are
                        replaced by 'dog', 1s by 'cat'.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_class_proportions(y_train, y_test, ['dog', 'cat', 'owl'])
    """
    if (test_missing(y_train=y_train, y_test=y_test) and
        test_types(y_train=y_train, y_test=y_test)):
        # Get the unique values from the dataset
        y_train = np.array(y_train)
        y_test = np.array(y_test)
        targets = (y_train,) if y_test is None else (y_train, y_test)
        classes_ = np.array(unique_labels(*targets))

        # Compute the class counts
        class_counts_train = np.array([(y_train == c).sum() for c in classes_])
        class_counts_test = np.array([(y_test == c).sum() for c in classes_])

        def class_proportions(classes_, class_counts_train, class_counts_test):
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
                if i >= chart_limit:
                    wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                    break

            if labels is not None and (isinstance(class_dict[0], int)
                                or isinstance(class_dict[0], np.integer)):
                class_dict = get_named_labels(labels, class_dict)
            return wandb.visualize(
                'wandb/class_proportions/v1', wandb.Table(
                columns=['class', 'dataset', 'count'],
                data=[
                    [class_dict[i], dataset_dict[i], count_dict[i]] for i in range(len(class_dict))
                ]
            ))
        wandb.log({'class_proportions': class_proportions(classes_, class_counts_train, class_counts_test)})


def plot_calibration_curve(clf=None, X=None, y=None, clf_name='Classifier'):
    """
    Plots how well calibrated the predicted probabilities of a classifier are and
        how to calibrate an uncalibrated classifier. Compares estimated predicted
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
        model (clf): Takes in a fitted classifier.
        X (arr): Training set features.
        y (arr): Training set labels.
        model_name (str): Model name. Defaults to 'Classifier'

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_calibration_curve(clf, X, y, 'RandomForestClassifier')
    """
    if (test_missing(clf=clf, X=X, y=y) and
        test_types(clf=clf, X=X, y=y) and
        test_fitted(clf)):
        y = np.asarray(y)
        # Create dataset of classification task with many redundant and few
        # informative features
        X, y = datasets.make_classification(n_samples=100000, n_features=20,
                                            n_informative=2, n_redundant=10,
                                            random_state=42)

        X_train, X_test, y_train, y_test = model_selection.train_test_split(X, y, test_size=0.99,
                                                            random_state=42)
        # Calibrated with isotonic calibration
        isotonic = CalibratedClassifierCV(clf, cv=2, method='isotonic')

        # Calibrated with sigmoid calibration
        sigmoid = CalibratedClassifierCV(clf, cv=2, method='sigmoid')

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

        X_train, X_test, y_train, y_test = model_selection.train_test_split(X, y, test_size=0.98,
                                                            random_state=42)

        # Add curve for LogisticRegression baseline and other models
        for clf, name in [(lr, 'Logistic'),
                          (clf, clf_name),
                          (isotonic, clf_name + ' + Isotonic'),
                          (sigmoid, clf_name + ' + Sigmoid')]:
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
                if i >= (chart_limit-2):
                    wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                    break

            def calibration_curves(model_dict, frac_positives_dict, mean_pred_value_dict, hist_dict, edge_dict):
                return wandb.visualize(
                    'wandb/calibration/v1', wandb.Table(
                    columns=['model', 'fraction_of_positives', 'mean_predicted_value', 'hist_dict', 'edge_dict'],
                    data=[
                        [model_dict[i], frac_positives_dict[i], mean_pred_value_dict[i], hist_dict[i], edge_dict[i]] for i in range(len(model_dict))
                    ]
                ))
        wandb.log({'calibration_curve': calibration_curves(model_dict, frac_positives_dict, mean_pred_value_dict, hist_dict, edge_dict)})


def plot_outlier_candidates(regressor=None, X=None, y=None):
    """
    Measures a datapoint's influence on regression model via cook's distance.
        Instances with heavily skewed influences could potentially be
        outliers. Useful for outlier detection.

    Should only be called with a fitted regressor (otherwise an error is thrown).
    Please note this function fits the model on the training set when called.

    Arguments:
        model (regressor): Takes in a fitted regressor.
        X (arr): Training set features.
        y (arr): Training set labels.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_outlier_candidates(model, X, y)
    """
    if (test_missing(regressor=regressor, X=X, y=y) and
        test_types(regressor=regressor, X=X, y=y) and
        test_fitted(regressor)):
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

        # Compute the p-values of Cook's Distance
        p_values_ = sp.stats.f.sf(distance_, X.shape[1], df)

        # Compute the influence threshold rule of thumb
        influence_threshold_ = 4 / X.shape[0]
        outlier_percentage_ = (
            sum(distance_ >= influence_threshold_) / X.shape[0]
        )
        outlier_percentage_ *= 100.0

        distance_dict = []
        count = 0
        for d in distance_:
            distance_dict.append(d)
            count+=1
            if count >= chart_limit:
                wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                break

        # Draw a stem plot with the influence for each instance
        # format: distance_, len(distance_), influence_threshold_, round_3(outlier_percentage_)
        def outlier_candidates(distance, outlier_percentage, influence_threshold):
            return wandb.visualize(
                'wandb/outliers/v1', wandb.Table(
                columns=['distance', 'instance_indicies', 'outlier_percentage', 'influence_threshold'],
                data=[
                    [distance[i], i, round_3(outlier_percentage_), influence_threshold_] for i in range(len(distance))
                ]
            ))
        wandb.log({'outlier_candidates': outlier_candidates(distance_dict, outlier_percentage_, influence_threshold_)})
        return


def plot_residuals(regressor=None, X=None, y=None):
    """
    Measures and plots the predicted target values (y-axis) vs the difference
        between actual and predicted target values (x-axis), as well as the
        distribution of the residual error.

    Should only be called with a fitted regressor (otherwise an error is thrown).
    Please note this function fits variations of the model on the training set when called.

    Arguments:
        model (regressor): Takes in a fitted regressor.
        X (arr): Training set features.
        y (arr): Training set labels.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_residuals(model, X, y)
    """
    if (test_missing(regressor=regressor, X=X, y=y) and
        test_types(regressor=regressor, X=X, y=y) and
        test_fitted(regressor)):
        y = np.asarray(y)
        # Create the train and test splits
        X_train, X_test, y_train, y_test = model_selection.train_test_split(X, y, test_size=0.2)

        # Store labels and colors for the legend ordered by call
        _labels, _colors = [], []
        regressor.fit(X_train, y_train)
        train_score_ = regressor.score(X_train, y_train)
        test_score_ = regressor.score(X_test, y_test)

        y_pred_train = regressor.predict(X_train)
        residuals_train = y_pred_train - y_train

        y_pred_test = regressor.predict(X_test)
        residuals_test = y_pred_test - y_test

        # format:
        # Legend: train_score_, test_score_ (play with opacity)
        # Scatterplot: dataset(train, test)(color), y_pred(x), residuals(y)
        # Histogram: dataset(train, test)(color), residuals(y), aggregate(residuals(x)) with bins=50
        def residuals(y_pred_train, residuals_train, y_pred_test, residuals_test, train_score_, test_score_):
            y_pred_dict = []
            dataset_dict = []
            residuals_dict = []
            datapoints = 0
            max_datapoints_train = 900
            max_datapoints_train = 100
            for pred, residual in zip(y_pred_train, residuals_train):
                # add class counts from training set
                y_pred_dict.append(pred)
                dataset_dict.append("train")
                residuals_dict.append(residual)
                datapoints += 1
                if(datapoints >= max_datapoints_train):
                    wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                    break
            datapoints = 0
            for pred, residual in zip(y_pred_test, residuals_test):
                # add class counts from training set
                y_pred_dict.append(pred)
                dataset_dict.append("test")
                residuals_dict.append(residual)
                datapoints += 1
                if(datapoints >= max_datapoints_train):
                    wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                    break

            return wandb.visualize(
                'wandb/residuals_plot/v1', wandb.Table(
                columns=['dataset', 'y_pred', 'residuals', 'train_score', 'test_score'],
                data=[
                    [dataset_dict[i], y_pred_dict[i], residuals_dict[i], train_score_, test_score_] for i in range(len(y_pred_dict))
                ]
            ))
        wandb.log({'residuals': residuals(y_pred_train, residuals_train, y_pred_test, residuals_test, train_score_, test_score_)})


def plot_decision_boundaries(binary_clf=None, X=None, y=None):
    """
    Visualizes decision boundaries by sampling from the feature space where the
        classifier's uncertainty > 0.5 and projecting these point to 2D space.
        Useful for measuring model (decision boundary) complexity, visualizing
        regions where the model falters and determine whether any over or
        underfitting occured.

    Should only be called with a fitted **binary** classifer (otherwise an error is
        thrown). Please note this function fits variations of the model on the
        training set when called.

    Arguments:
        model (clf): Takes in a fitted binary classifier.
        X_train (arr): Training set features.
        y_train (arr): Training set labels.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.sklearn.plot_decision_boundaries(binary_classifier, X, y)
    """
    if (test_missing(binary_clf=binary_clf, X=X, y=y) and
        test_types(binary_clf=binary_clf, X=X, y=y)):
        y = np.asarray(y)
        # plot high-dimensional decision boundary
        db = DBPlot(binary_clf)
        db.fit(X, y)
        decision_boundary_x, decision_boundary_y, decision_boundary_color, train_x, train_y, train_color, test_x, test_y, test_color = db.plot()
        def decision_boundaries(decision_boundary_x, decision_boundary_y,
                                decision_boundary_color, train_x, train_y,
                                train_color, test_x, test_y, test_color):
            x_dict = []
            y_dict = []
            color_dict = []
            shape_dict = []
            for i in range(min(len(decision_boundary_x),100)):
                x_dict.append(decision_boundary_x[i])
                y_dict.append(decision_boundary_y[i])
                color_dict.append(decision_boundary_color)
            for i in range(300):
                x_dict.append(test_x[i])
                y_dict.append(test_y[i])
                color_dict.append(test_color[i])
            for i in range(min(len(train_x),600)):
                x_dict.append(train_x[i])
                y_dict.append(train_y[i])
                color_dict.append(train_color[i])

            return wandb.visualize(
                'wandb/decision_boundaries/v1', wandb.Table(
                columns=['x', 'y', 'color'],
                data=[
                    [x_dict[i], y_dict[i], color_dict[i]] for i in range(len(x_dict))
                ]
            ))
        wandb.log({'decision_boundaries': decision_boundaries(decision_boundary_x,
                                    decision_boundary_y, decision_boundary_color,
                                    train_x, train_y, train_color, test_x, test_y,
                                test_color)})
