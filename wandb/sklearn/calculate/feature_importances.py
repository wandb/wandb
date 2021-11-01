from warnings import simplefilter

import wandb

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def make_feature_importances_table(feature_names, importances):
    return wandb.visualize(
        "wandb/feature_importances/v1",
        wandb.Table(columns=["feature_names", "importances"], data=[],),
    )
