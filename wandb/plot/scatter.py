from __future__ import annotations

import wandb
from wandb.plot.custom_chart import CustomChart


def scatter(
    table: wandb.Table,
    x: str,
    y: str,
    title: str = "",
    split_table: bool = False,
) -> CustomChart:
    """Constructs a scatter plot from a wandb.Table of data.

    Args:
        table (wandb.Table): The W&B Table containing the data to visualize.
        x (str): The name of the column used for the x-axis.
        y (str): The name of the column used for the y-axis.
        title (string): The title of the scatter chart.
        split_table (bool): Whether to split the table into a different section
            in the UI. Default is False.

    Returns:
        A scatter chart that can be logged to W&B with `wandb.log()`.

    Example:
        ```
        import math
        import random
        import wandb

        # Simulate temperature variations at different altitudes over time
        data = [
            [i, random.uniform(-10, 20) - 0.005 * i + 5 * math.sin(i / 50)] for i in range(300)
        ]

        # Create W&B table with altitude (m) and temperature (°C) columns
        table = wandb.Table(data=data, columns=["altitude (m)", "temperature (°C)"])

        # Initialize W&B run and log the scatter plot
        with wandb.init(project="temperature-altitude-scatter") as run:
            # Create and log the scatter plot
            scatter_plot = wandb.plot.scatter(
                table=table,
                x="altitude (m)",
                y="temperature (°C)",
                title="Altitude vs Temperature",
            )
            run.log({"altitude-temperature-scatter": scatter_plot})
        ```
    """
    return CustomChart(
        id="wandb/scatter/v0",
        data=table,
        fields={"x": x, "y": y},
        string_fields={"title": title},
        split_table=split_table,
    )
