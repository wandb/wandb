"""Logs sklearn model plots to W&B."""
from warnings import simplefilter

import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import silhouette_score, silhouette_samples
from sklearn.preprocessing import LabelEncoder

import wandb

from wandb.sklearn import utils
from wandb.sklearn import calculate


# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def clusterer(model, X_train, cluster_labels, labels=None, model_name="Clusterer"):
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
        elbow_curve(model, X_train)
        wandb.termlog("Logged elbow curve.")
        silhouette(model, X_train, cluster_labels, labels=labels, kmeans=True)
    else:
        silhouette(model, X_train, cluster_labels, kmeans=False)
    wandb.termlog("Logged silhouette plot.")


def elbow_curve(
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

        wandb.log(
            {
                "elbow_curve": calculate.make_elbow_curve_table(
                    cluster_ranges, clfs, times
                )
            }
        )
        return


def silhouette(
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

        x_sil, y_sil, color_sil = [], [], []

        count, y_lower = 0, 10
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
                if utils.check_against_limit(count, utils.CHART_LIMIT, "silhouette"):
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
