"""The silhouette chart covers every cluster label, not just 0..k-1."""

from collections import Counter

import numpy as np
import pytest

pytest.importorskip("sklearn")

from wandb.integration.sklearn import calculate

X = np.array([[0.0, 0.0], [0.1, 0.0], [5.0, 5.0], [5.1, 5.0], [9.0, 0.0], [9.1, 0.0]])


@pytest.mark.parametrize(
    "cluster_labels",
    [
        [0, 0, 1, 1, 2, 2],
        [1, 1, 2, 2, 3, 3],  # numbered from 1
        [-1, -1, 0, 0, 1, 1],  # DBSCAN-style noise label
    ],
)
def test_every_sample_gets_a_silhouette_row(cluster_labels):
    chart = calculate.silhouette(
        None, X, cluster_labels, None, "euclidean", kmeans=False
    )

    color_sil = chart.table.get_column("color_sil")
    assert Counter(color_sil) == Counter(cluster_labels)
