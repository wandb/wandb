from typing import TYPE_CHECKING, Optional

from wandb.plot.viz import custom_chart

if TYPE_CHECKING:
    import wandb


def histogram(
    table: "wandb.Table",
    value: str,
    title: Optional[str] = None,
    split_table: Optional[bool] = False,
):
    """Construct a histogram plot.

    Arguments:
        table (wandb.Table): Table of data.
        value (string): Name of column to use as data for bucketing.
        title (string): Plot title.
        split_table (bool): If True, adds "Custom Chart Tables/" to the key of the table so that it's logged in a different section.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]
        table = wandb.Table(data=data, columns=["step", "height"])
        wandb.log({'histogram-plot1': wandb.plot.histogram(table, "height")})
        ```
    """
    return custom_chart(
        "wandb/histogram/v0",
        table,
        {"value": value},
        {"title": title},
        split_table=split_table,
    )
