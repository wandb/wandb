from warnings import simplefilter

import wandb

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def make_elbow_curve_table(cluster_ranges, clfs, times):
    return wandb.visualize(
        "wandb/elbow/v1",
        wandb.Table(
            columns=["cluster_ranges", "errors", "clustering_time"],
            data=[
                [cluster_ranges[i], clfs[i], times[i]]
                for i in range(len(cluster_ranges))
            ],
        ),
    )
