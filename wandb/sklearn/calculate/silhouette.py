from warnings import simplefilter

import wandb

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def silhouette(x, y, colors, centerx, centery, y_sil, x_sil, color_sil, silhouette_avg):
    return wandb.visualize(
        "wandb/silhouette_/v1",
        wandb.Table(
            columns=[
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
            ],
            data=[
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
            ],
        ),
    )


def silhouette_(
    x, y, colors, centerx, centery, y_sil, x_sil, color_sil, silhouette_avg
):
    return wandb.visualize(
        "wandb/silhouette_/v1",
        wandb.Table(
            columns=[
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
            ],
            data=[
                [
                    x[i],
                    y[i],
                    colors[i],
                    None,
                    None,
                    y_sil[i],
                    0,
                    x_sil[i],
                    color_sil[i],
                    silhouette_avg,
                ]
                for i in range(len(color_sil))
            ],
        ),
    )
