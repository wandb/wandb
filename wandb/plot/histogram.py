from __future__ import annotations

from typing import TYPE_CHECKING

from wandb.plot.custom_chart import plot_table

if TYPE_CHECKING:
    import wandb
    from wandb.plot.custom_chart import CustomChart


def histogram(
    table: wandb.Table,
    value: str,
    title: str = "",
    split_table: bool = False,
) -> CustomChart:
    """Constructs a histogram chart from a W&B Table.

    Args:
        table: The W&B Table containing the data for the histogram.
        value: The label for the bin axis (x-axis).
        title: The title of the histogram plot.
        split_table: Whether the table should be split into a separate section
            in the W&B UI. If `True`, the table will be displayed in a section named
            "Custom Chart Tables". Default is `False`.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass it to `wandb.log()`.

    Example:

    ```python
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
        run.log({"histogram-plot1": histogram})
    ```
    """
    return plot_table(
        data_table=table,
        vega_spec_name="wandb/histogram/v0",
        fields={"value": value},
        string_fields={"title": title},
        split_table=split_table,
    )
