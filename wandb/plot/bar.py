from __future__ import annotations

from typing import TYPE_CHECKING

from wandb.plot.viz import CustomChart

if TYPE_CHECKING:
    import wandb


def bar(
    table: wandb.Table,
    label: str,
    value: str,
    title: str = "",
    split_table: bool = False,
) -> CustomChart:
    """Constructs a bar chart from a wandb.Table of data.

    Args:
        table (wandb.Table): A table containing the data for the bar chart.
        label (str): The name of the column to use for the labels of each bar.
        value (str): The name of the column to use for the values of each bar.
        title (str): The title of the bar chart.
        split_table (bool): Whether to split the table into a different section
            in the UI. Default is False.

    Returns:
        CustomChart: A bar chart. That can be logged to W&B with
            `wandb.log({'bar-plot1': bar_plot})`.

    Example:
        ```
        import random
        import wandb

        # Generate random data for the table
        data = [
            ['car', random.uniform(0, 1)],
            ['bus', random.uniform(0, 1)],
            ['road', random.uniform(0, 1)],
            ['person', random.uniform(0, 1)],
        ]

        # Create a table with the data
        table = wandb.Table(data=data, columns=["class", "accuracy"])

        # Initialize a W&B run and log the bar plot
        with wandb.init(project="bar_chart") as run:

            # Create a bar plot from the table
            bar_plot = wandb.plot.bar(
                table=table,
                label="class",
                value="accuracy",
                title="Object Classification Accuracy",
            )

            # Log the bar chart to W&B
            run.log({'bar_plot': bar_plot})
        ```
    """
    return CustomChart(
        id="wandb/bar/v0",
        data=table,
        fields={"label": label, "value": value},
        string_fields={"title": title},
        split_table=split_table,
    )
