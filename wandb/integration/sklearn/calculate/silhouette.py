from warnings import simplefilter

import numpy as np
from sklearn.metrics import silhouette_samples, silhouette_score
from sklearn.preprocessing import LabelEncoder

import wandb
from wandb.integration.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def silhouette(clusterer, X, cluster_labels, labels, metric, kmeans):  # noqa: N803
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

    x_sil, y_sil, color_sil = [], [], []

    count, y_lower = 0, 10
    for i in range(n_clusters):
        # Aggregate the silhouette scores for samples belonging to
        # cluster i, and sort them
        ith_cluster_silhouette_values = sample_silhouette_values[cluster_labels == i]

        ith_cluster_silhouette_values.sort()

        size_cluster_i = ith_cluster_silhouette_values.shape[0]
        y_upper = y_lower + size_cluster_i

        y_values = np.arange(y_lower, y_upper)

        for j in range(len(y_values)):
            y_sil.append(y_values[j])
            x_sil.append(ith_cluster_silhouette_values[j])
            color_sil.append(i)
            count += 1
            if utils.check_against_limit(count, "silhouette", utils.chart_limit):
                break

        # Compute the new y_lower for next plot
        y_lower = y_upper + 10  # 10 for the 0 samples

    if kmeans:
        centers = clusterer.cluster_centers_
        centerx = centers[:, 0]
        centery = centers[:, 1]

    else:
        centerx = [None] * len(color_sil)
        centery = [None] * len(color_sil)

    table = make_table(
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
    chart = wandb.visualize("wandb/silhouette_/v1", table)

    return chart


def make_table(x, y, colors, centerx, centery, y_sil, x_sil, color_sil, silhouette_avg):
    columns = [
        "x",
        "y",
        "colors",
        "centerx",
        "centery",
        "y_sil",
        "x1",
        "x2",
        "color_sil",
        "silhouette_avg",
    ]

    data = [
        [
            x[i],
            y[i],
            colors[i],
            centerx[colors[i]],
            centery[colors[i]],
            y_sil[i],
            0,
            x_sil[i],
            color_sil[i],
            silhouette_avg,
        ]
        for i in range(len(color_sil))
    ]

    table = wandb.Table(data=data, columns=columns)

    return table
