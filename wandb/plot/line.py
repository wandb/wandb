from __future__ import annotations

from typing import TYPE_CHECKING

from wandb.plot.custom_chart import plot_table

if TYPE_CHECKING:
    import wandb
    from wandb.plot.custom_chart import CustomChart


def line(
    table: wandb.Table,
    x: str,
    y: str,
    stroke: str | None = None,
    title: str = "",
    split_table: bool = False,
) -> CustomChart:
    """Constructs a customizable line chart.

    Args:
        table:  The table containing data for the chart.
        x: Column name for the x-axis values.
        y: Column name for the y-axis values.
        stroke: Column name to differentiate line strokes (e.g., for
            grouping lines).
        title: Title of the chart.
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

    # Create multiple series of data with different patterns
    data = []
    for i in range(100):
        # Series 1: Sinusoidal pattern with random noise
        data.append([i, math.sin(i / 10) + random.uniform(-0.1, 0.1), "series_1"])
        # Series 2: Cosine pattern with random noise
        data.append([i, math.cos(i / 10) + random.uniform(-0.1, 0.1), "series_2"])
        # Series 3: Linear increase with random noise
        data.append([i, i / 10 + random.uniform(-0.5, 0.5), "series_3"])

    # Define the columns for the table
    table = wandb.Table(data=data, columns=["step", "value", "series"])

    # Initialize wandb run and log the line chart
    with wandb.init(project="line_chart_example") as run:
        line_chart = wandb.plot.line(
            table=table,
            x="step",
            y="value",
            stroke="series",  # Group by the "series" column
            title="Multi-Series Line Plot",
        )
        run.log({"line-chart": line_chart})
    ```
    """
    return plot_table(
        data_table=table,
        vega_spec_name="wandb/line/v0",
        fields={"x": x, "y": y, "stroke": stroke},
        string_fields={"title": title},
        split_table=split_table,
    )
