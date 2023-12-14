from typing import Optional

import wandb


def scatter(table, x, y, title=None, split_table: Optional[bool] = False):
    """Construct a scatter plot.

    Arguments:
        table (wandb.Table): Table of data.
        x (string): Name of column to as for x-axis values.
        y (string): Name of column to as for y-axis values.
        title (string): Plot title.
        split_table (bool): If True, adds "Custom Chart Tables/" to the key of the table so that it's logged in a different section.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]
        table = wandb.Table(data=data, columns=["step", "height"])
        wandb.log({'scatter-plot1': wandb.plot.scatter(table, "step", "height")})
        ```
    """
    return wandb.plot_table(
        "wandb/scatter/v0",
        table,
        {"x": x, "y": y},
        {"title": title},
        split_table=split_table,
    )
