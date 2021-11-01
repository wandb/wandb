from warnings import simplefilter


import wandb
from wandb.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def outlier_candidates(distance, outlier_percentage, influence_threshold):
    return wandb.visualize(
        "wandb/outliers/v1",
        wandb.Table(
            columns=[
                "distance",
                "instance_indicies",
                "outlier_percentage",
                "influence_threshold",
            ],
            data=[
                [
                    distance[i],
                    i,
                    utils.round_3(outlier_percentage),
                    influence_threshold,
                ]
                for i in range(len(distance))
            ],
        ),
    )
