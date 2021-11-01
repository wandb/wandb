from warnings import simplefilter

import wandb

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def calibration_curves(
    model_dict,
    frac_positives_dict,
    mean_pred_value_dict,
    hist_dict,
    edge_dict,
):
    return wandb.visualize(
        "wandb/calibration/v1",
        wandb.Table(
            columns=[
                "model",
                "fraction_of_positives",
                "mean_predicted_value",
                "hist_dict",
                "edge_dict",
            ],
            data=[
                [
                    model_dict[i],
                    frac_positives_dict[i],
                    mean_pred_value_dict[i],
                    hist_dict[i],
                    edge_dict[i],
                ]
                for i in range(len(model_dict))
            ],
        ),
    )
