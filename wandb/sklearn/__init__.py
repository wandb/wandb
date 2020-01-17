from __future__ import absolute_import, division, print_function, unicode_literals
import wandb
import sklearn
import numpy as np
import scikitplot
import matplotlib.pyplot as plt
from keras.callbacks import LambdaCallback
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
        data=[]
        for i in range(len(train)):
            data.append(["train"], train[i], trainsize[i])
            data.append(["test"], test[i], trainsize[i])
        return wandb.Table(
            columns=['dataset', 'score', 'train_size'],
            data=data
        )
    wandb.log({'learning_curve': confusion(train_scores_mean, test_scores_mean, train_sizes)})
    return

def plot_confusion_matrix(y_true, y_pred, labels=None, true_labels=None,
                          pred_labels=None, title=None, normalize=False,
                          hide_zeros=False, hide_counts=False, x_tick_rotation=0, ax=None,
                          figsize=None, cmap='Blues', title_fontsize="large",
                          text_fontsize="medium"):
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    cm = confusion_matrix(y_true, y_pred, labels=labels)
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

    if title:
        ax.set_title(title, fontsize=title_fontsize)
    elif normalize:
        ax.set_title('Normalized Confusion Matrix', fontsize=title_fontsize)
    else:
        ax.set_title('Confusion Matrix', fontsize=title_fontsize)

    image = ax.imshow(cm, interpolation='nearest', cmap=plt.cm.get_cmap(cmap))
    plt.colorbar(mappable=image)
    x_tick_marks = np.arange(len(pred_classes))
    y_tick_marks = np.arange(len(true_classes))
    ax.set_xticks(x_tick_marks)
    ax.set_xticklabels(pred_classes, fontsize=text_fontsize,
                       rotation=x_tick_rotation)
    ax.set_yticks(y_tick_marks)
    ax.set_yticklabels(true_classes, fontsize=text_fontsize)

    thresh = cm.max() / 2.

    if not hide_counts:
        for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
            if not (hide_zeros and cm[i, j] == 0):
                ax.text(j, i, cm[i, j],
                        horizontalalignment="center",
                        verticalalignment="center",
                        fontsize=text_fontsize,
                        color="white" if cm[i, j] > thresh else "black")

    ax.set_ylabel('True label', fontsize=text_fontsize)
    ax.set_xlabel('Predicted label', fontsize=text_fontsize)
    ax.grid(False)

    return ax


def plot_roc(y_true, y_probas, title='ROC Curves',
                   plot_micro=True, plot_macro=True, classes_to_plot=None,
                   ax=None, figsize=None, cmap='nipy_spectral',
                   title_fontsize="large", text_fontsize="medium"):
    y_true = np.array(y_true)
    y_probas = np.array(y_probas)

    classes = np.unique(y_true)
    probas = y_probas

    if classes_to_plot is None:
        classes_to_plot = classes

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    ax.set_title(title, fontsize=title_fontsize)

    fpr_dict = dict()
    tpr_dict = dict()

    indices_to_plot = np.in1d(classes, classes_to_plot)
    for i, to_plot in enumerate(indices_to_plot):
        fpr_dict[i], tpr_dict[i], _ = roc_curve(y_true, probas[:, i],
                                                pos_label=classes[i])
        if to_plot:
            roc_auc = auc(fpr_dict[i], tpr_dict[i])
            color = plt.cm.get_cmap(cmap)(float(i) / len(classes))
            ax.plot(fpr_dict[i], tpr_dict[i], lw=2, color=color,
                    label='ROC curve of class {0} (area = {1:0.2f})'
                          ''.format(classes[i], roc_auc))

    if plot_micro:
        binarized_y_true = label_binarize(y_true, classes=classes)
        if len(classes) == 2:
            binarized_y_true = np.hstack(
                (1 - binarized_y_true, binarized_y_true))
        fpr, tpr, _ = roc_curve(binarized_y_true.ravel(), probas.ravel())
        roc_auc = auc(fpr, tpr)
        ax.plot(fpr, tpr,
                label='micro-average ROC curve '
                      '(area = {0:0.2f})'.format(roc_auc),
                color='deeppink', linestyle=':', linewidth=4)

    if plot_macro:
        # Compute macro-average ROC curve and ROC area
        # First aggregate all false positive rates
        all_fpr = np.unique(np.concatenate([fpr_dict[x] for x in range(len(classes))]))

        # Then interpolate all ROC curves at this points
        mean_tpr = np.zeros_like(all_fpr)
        for i in range(len(classes)):
            mean_tpr += interp(all_fpr, fpr_dict[i], tpr_dict[i])

        # Finally average it and compute AUC
        mean_tpr /= len(classes)
        roc_auc = auc(all_fpr, mean_tpr)

        ax.plot(all_fpr, mean_tpr,
                label='macro-average ROC curve '
                      '(area = {0:0.2f})'.format(roc_auc),
                color='navy', linestyle=':', linewidth=4)

    ax.plot([0, 1], [0, 1], 'k--', lw=2)
    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel('False Positive Rate', fontsize=text_fontsize)
    ax.set_ylabel('True Positive Rate', fontsize=text_fontsize)
    ax.tick_params(labelsize=text_fontsize)
    ax.legend(loc='lower right', fontsize=text_fontsize)
    return ax


def plot_ks_statistic(y_true, y_probas, title='KS Statistic Plot',
                      ax=None, figsize=None, title_fontsize="large",
                      text_fontsize="medium"):
    y_true = np.array(y_true)
    y_probas = np.array(y_probas)

    classes = np.unique(y_true)
    if len(classes) != 2:
        raise ValueError('Cannot calculate KS statistic for data with '
                         '{} category/ies'.format(len(classes)))
    probas = y_probas

    # Compute KS Statistic curves
    thresholds, pct1, pct2, ks_statistic, \
        max_distance_at, classes = binary_ks_curve(y_true,
                                                   probas[:, 1].ravel())

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    ax.set_title(title, fontsize=title_fontsize)

    ax.plot(thresholds, pct1, lw=3, label='Class {}'.format(classes[0]))
    ax.plot(thresholds, pct2, lw=3, label='Class {}'.format(classes[1]))
    idx = np.where(thresholds == max_distance_at)[0][0]
    ax.axvline(max_distance_at, *sorted([pct1[idx], pct2[idx]]),
               label='KS Statistic: {:.3f} at {:.3f}'.format(ks_statistic,
                                                             max_distance_at),
               linestyle=':', lw=3, color='black')

    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.0])

    ax.set_xlabel('Threshold', fontsize=text_fontsize)
    ax.set_ylabel('Percentage below threshold', fontsize=text_fontsize)
    ax.tick_params(labelsize=text_fontsize)
    ax.legend(loc='lower right', fontsize=text_fontsize)

    return ax


def plot_precision_recall(y_true, y_probas,
                          title='Precision-Recall Curve',
                          plot_micro=True,
                          classes_to_plot=None, ax=None,
                          figsize=None, cmap='nipy_spectral',
                          title_fontsize="large",
                          text_fontsize="medium"):
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

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    ax.set_title(title, fontsize=title_fontsize)

    indices_to_plot = np.in1d(classes, classes_to_plot)
    for i, to_plot in enumerate(indices_to_plot):
        if to_plot:
            average_precision = average_precision_score(
                binarized_y_true[:, i],
                probas[:, i])
            precision, recall, _ = precision_recall_curve(
                y_true, probas[:, i], pos_label=classes[i])
            color = plt.cm.get_cmap(cmap)(float(i) / len(classes))
            ax.plot(recall, precision, lw=2,
                    label='Precision-recall curve of class {0} '
                          '(area = {1:0.3f})'.format(classes[i],
                                                     average_precision),
                    color=color)

    if plot_micro:
        precision, recall, _ = precision_recall_curve(
            binarized_y_true.ravel(), probas.ravel())
        average_precision = average_precision_score(binarized_y_true,
                                                    probas,
                                                    average='micro')
        ax.plot(recall, precision,
                label='micro-average Precision-recall curve '
                      '(area = {0:0.3f})'.format(average_precision),
                color='navy', linestyle=':', linewidth=4)

    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel('Recall')
    ax.set_ylabel('Precision')
    ax.tick_params(labelsize=text_fontsize)
    ax.legend(loc='best', fontsize=text_fontsize)
    return ax


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


def plot_calibration_curve(y_true, probas_list, clf_names=None, n_bins=10,
                           title='Calibration plots (Reliability Curves)',
                           ax=None, figsize=None, cmap='nipy_spectral',
                           title_fontsize="large", text_fontsize="medium"):
    y_true = np.asarray(y_true)
    if not isinstance(probas_list, list):
        raise ValueError('`probas_list` does not contain a list.')

    classes = np.unique(y_true)
    if len(classes) > 2:
        raise ValueError('plot_calibration_curve only '
                         'works for binary classification')

    if clf_names is None:
        clf_names = ['Classifier {}'.format(x+1)
                     for x in range(len(probas_list))]

    if len(clf_names) != len(probas_list):
        raise ValueError('Length {} of `clf_names` does not match length {} of'
                         ' `probas_list`'.format(len(clf_names),
                                                 len(probas_list)))

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    ax.plot([0, 1], [0, 1], "k:", label="Perfectly calibrated")

    for i, probas in enumerate(probas_list):
        probas = np.asarray(probas)
        if probas.ndim > 2:
            raise ValueError('Index {} in probas_list has invalid '
                             'shape {}'.format(i, probas.shape))
        if probas.ndim == 2:
            probas = probas[:, 1]

        if probas.shape != y_true.shape:
            raise ValueError('Index {} in probas_list has invalid '
                             'shape {}'.format(i, probas.shape))

        probas = (probas - probas.min()) / (probas.max() - probas.min())

        fraction_of_positives, mean_predicted_value = \
            calibration_curve(y_true, probas, n_bins=n_bins)

        color = plt.cm.get_cmap(cmap)(float(i) / len(probas_list))

        ax.plot(mean_predicted_value, fraction_of_positives, 's-',
                label=clf_names[i], color=color)

    ax.set_title(title, fontsize=title_fontsize)

    ax.set_xlabel('Mean predicted value', fontsize=text_fontsize)
    ax.set_ylabel('Fraction of positives', fontsize=text_fontsize)

    ax.set_ylim([-0.05, 1.05])
    ax.legend(loc='lower right')

    return ax


def plot_cumulative_gain(y_true, y_probas, title='Cumulative Gains Curve',
                         ax=None, figsize=None, title_fontsize="large",
                         text_fontsize="medium"):
    y_true = np.array(y_true)
    y_probas = np.array(y_probas)

    classes = np.unique(y_true)
    if len(classes) != 2:
        raise ValueError('Cannot calculate Cumulative Gains for data with '
                         '{} category/ies'.format(len(classes)))

    # Compute Cumulative Gain Curves
    percentages, gains1 = cumulative_gain_curve(y_true, y_probas[:, 0],
                                                classes[0])
    percentages, gains2 = cumulative_gain_curve(y_true, y_probas[:, 1],
                                                classes[1])

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    ax.set_title(title, fontsize=title_fontsize)

    ax.plot(percentages, gains1, lw=3, label='Class {}'.format(classes[0]))
    ax.plot(percentages, gains2, lw=3, label='Class {}'.format(classes[1]))

    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.0])

    ax.plot([0, 1], [0, 1], 'k--', lw=2, label='Baseline')

    ax.set_xlabel('Percentage of sample', fontsize=text_fontsize)
    ax.set_ylabel('Gain', fontsize=text_fontsize)
    ax.tick_params(labelsize=text_fontsize)
    ax.grid('on')
    ax.legend(loc='lower right', fontsize=text_fontsize)

    return ax


def plot_lift_curve(y_true, y_probas, title='Lift Curve',
                    ax=None, figsize=None, title_fontsize="large",
                    text_fontsize="medium"):
    y_true = np.array(y_true)
    y_probas = np.array(y_probas)

    classes = np.unique(y_true)
    if len(classes) != 2:
        raise ValueError('Cannot calculate Lift Curve for data with '
                         '{} category/ies'.format(len(classes)))

    # Compute Cumulative Gain Curves
    percentages, gains1 = cumulative_gain_curve(y_true, y_probas[:, 0],
                                                classes[0])
    percentages, gains2 = cumulative_gain_curve(y_true, y_probas[:, 1],
                                                classes[1])

    percentages = percentages[1:]
    gains1 = gains1[1:]
    gains2 = gains2[1:]

    gains1 = gains1 / percentages
    gains2 = gains2 / percentages

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)

    ax.set_title(title, fontsize=title_fontsize)

    ax.plot(percentages, gains1, lw=3, label='Class {}'.format(classes[0]))
    ax.plot(percentages, gains2, lw=3, label='Class {}'.format(classes[1]))

    ax.plot([0, 1], [1, 1], 'k--', lw=2, label='Baseline')

    ax.set_xlabel('Percentage of sample', fontsize=text_fontsize)
    ax.set_ylabel('Lift', fontsize=text_fontsize)
    ax.tick_params(labelsize=text_fontsize)
    ax.grid('on')
    ax.legend(loc='lower right', fontsize=text_fontsize)

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
