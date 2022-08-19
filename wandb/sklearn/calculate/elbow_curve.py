import time
from warnings import simplefilter

import numpy as np
from joblib import Parallel, delayed
from sklearn.base import clone

import wandb

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def elbow_curve(clusterer, X, cluster_ranges, n_jobs, show_cluster_time):
    if cluster_ranges is None:
        cluster_ranges = range(1, 10, 2)
    else:
        cluster_ranges = sorted(cluster_ranges)

    clfs, times = _compute_results_parallel(n_jobs, clusterer, X, cluster_ranges)

    clfs = np.absolute(clfs)

    table = make_table(cluster_ranges, clfs, times)
    chart = wandb.visualize("wandb/elbow/v1", table)

    return chart


def make_table(cluster_ranges, clfs, times):
    columns = ["cluster_ranges", "errors", "clustering_time"]

    data = list(zip(cluster_ranges, clfs, times))

    table = wandb.Table(columns=columns, data=data)

    return table


def _compute_results_parallel(n_jobs, clusterer, X, cluster_ranges):
    parallel_runner = Parallel(n_jobs=n_jobs)
    _cluster_scorer = delayed(_clone_and_score_clusterer)
    results = parallel_runner(_cluster_scorer(clusterer, X, i) for i in cluster_ranges)

    clfs, times = zip(*results)

    return clfs, times


def _clone_and_score_clusterer(clusterer, X, n_clusters):
    start = time.time()
    clusterer = clone(clusterer)
    setattr(clusterer, "n_clusters", n_clusters)

    return clusterer.fit(X).score(X), time.time() - start
