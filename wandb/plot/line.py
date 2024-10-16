from typing import TYPE_CHECKING, Optional

from wandb.plot.viz import custom_chart

if TYPE_CHECKING:
    import wandb


def line(
    table: "wandb.Table",
    x: str,
    y: str,
    stroke: Optional[str] = None,
    title: Optional[str] = None,
    split_table: Optional[bool] = False,
):
    """Construct a line plot.

    Arguments:
        table (wandb.Table): Table of data.
        x (string): Name of column to as for x-axis values.
        y (string): Name of column to as for y-axis values.
        stroke (string): Name of column to map to the line stroke scale.
        title (string): Plot title.
        split_table (bool): If True, adds "Custom Chart Tables/" to the key of the table so that it's logged in a different section.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]
        table = wandb.Table(data=data, columns=["step", "height"])
        wandb.log({'line-plot1': wandb.plot.line(table, "step", "height")})
        ```
    """
    return custom_chart(
        "wandb/line/v0",
        table,
        {"x": x, "y": y, "stroke": stroke},
        {"title": title},
        split_table=split_table,
    )
