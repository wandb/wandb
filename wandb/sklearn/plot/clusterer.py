"""Define plots for clustering models built with scikit-learn."""

from warnings import simplefilter

import pandas as pd
import sklearn

import wandb
from wandb.sklearn import calculate, utils

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
        labels: (list) Named labels for target variable (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example if `labels=['dog', 'cat', 'owl']` all 0s are
                        replaced by dog, 1s by cat.
        model_name: (str) Model name. Defaults to 'Clusterer'

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
    wandb.sklearn.plot_clusterer(kmeans, X, cluster_labels, labels, "KMeans")
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

    not_missing = utils.test_missing(clusterer=clusterer)
    correct_types = utils.test_types
    is_fitted = utils.test_fitted(clusterer)

    if not_missing and correct_types and is_fitted:
        elbow_curve_chart = calculate.elbow_curve(
            clusterer, X, cluster_ranges, n_jobs, show_cluster_time
        )

        wandb.log({"elbow_curve": elbow_curve_chart})


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
    wandb.sklearn.plot_silhouette(model, X_train, ["spam", "not spam"])
    ```
    """
    not_missing = utils.test_missing(clusterer=clusterer)
    correct_types = utils.test_types(clusterer=clusterer)
    is_fitted = utils.test_fitted(clusterer)

    if not_missing and correct_types and is_fitted:
        if isinstance(X, (pd.DataFrame)):
            X = X.values
        silhouette_chart = calculate.silhouette(
            clusterer, X, cluster_labels, labels, metric, kmeans
        )
        wandb.log({"silhouette_plot": silhouette_chart})
