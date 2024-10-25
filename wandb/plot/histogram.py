from __future__ import annotations

from typing import TYPE_CHECKING

from wandb.plot.viz import CustomChart

if TYPE_CHECKING:
    import wandb


def histogram(
    table: wandb.Table,
    value: str,
    title: str = "",
    split_table: bool = False,
):
    """Constructs a histogram chart from a W&B Table.

    Args:
        table (wandb.Table): The W&B Table containing the data for the histogram.
        value (str): The label for the bin axis (x-axis).
        title (str): The title of the histogram plot.
        split_table (bool): Whether to split the table into a different section
            in the UI. Default is False.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass it to `wandb.log()`.

    Example:
        ```
        import math
        import random
        import wandb

        # Generate random data
        data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]

        # Create a W&B Table
        table = wandb.Table(
            data=data,
            columns=["step", "height"],
        )

        # Create a histogram plot
        histogram = wandb.plot.histogram(
            table,
            value="height",
            title="My Histogram",
        )

        # Log the histogram plot to W&B
        with wandb.init(...) as run:
            run.log({'histogram-plot1': histogram})
        ```
    """
    return CustomChart(
        id="wandb/histogram/v0",
        data=table,
        fields={"value": value},
        string_fields={"title": title},
        split_table=split_table,
    )
