from typing import Optional

import wandb


def histogram(table: wandb.Table, value: str, title: Optional[str] = None, log_table_separately: Optional[bool] = False):
    """Construct a histogram plot.

    Arguments:
        table (wandb.Table): Table of data.
        value (string): Name of column to use as data for bucketing.
        title (string): Plot title.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]
        table = wandb.Table(data=data, columns=["step", "height"])
        wandb.log({'histogram-plot1': wandb.plot.histogram(table, "height")})
        ```
    """
    return wandb.plot_table(
        "wandb/histogram/v0", table, {"value": value}, {"title": title}, log_table_separately=log_table_separately
    )
