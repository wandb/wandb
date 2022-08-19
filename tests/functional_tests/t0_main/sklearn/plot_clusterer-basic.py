#!/usr/bin/env python
"""Demonstrate basic API of plot_clusterer.
---
id: 0.sklearn.plot_clusterer-basic
tag:
  shard: sklearn
plugin:
    - wandb
depend:
    requirements:
        - numpy
        - scikit-learn
assert:
    - :wandb:runs_len: 1
    - :wandb:runs[0][exitcode]: 0
    - :wandb:runs[0][summary][elbow_curve][_type]: table-file
    - :wandb:runs[0][summary][elbow_curve][ncols]: 3
    - :wandb:runs[0][summary][silhouette_plot][_type]: table-file
    - :wandb:runs[0][summary][silhouette_plot][ncols]: 10
    - :yea:exit: 0
"""
import numpy as np
import wandb
from sklearn import datasets
from sklearn.cluster import KMeans

wandb.init("my-scikit-integration")

iris = datasets.load_iris()
X, y = iris.data, iris.target

names = iris.target_names
labels = np.array([names[target] for target in y])

kmeans = KMeans(n_clusters=4, random_state=1)

cluster_labels = kmeans.fit_predict(X)

wandb.sklearn.plot_clusterer(kmeans, X, cluster_labels, labels, "KMeans")
