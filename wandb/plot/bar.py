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
):
    """Constructs a bar chart from a wandb.Table of data.

    Args:
        table (wandb.Table): The W&B Table containing the data to visualize.
        label (str): Title of the categorical axis (y-axis).
        value (str): Title of the numerical axis (x-axis).
        title (str): Title of the bar plot.
        split_table (bool): Whether to split the table into a different section
            in the UI. Default is False.

    Returns:
        CustomChart: A bar plot. That can be logged to W&B with
            `wandb.log({'bar-plot1': bar_plot})`.

    Example:
        ```
        import random
        import wandb

        # Create a table with random data
        table = wandb.Table(data=[
            ['car', random.random()],
            ['bus', random.random()],
            ['road', random.random()],
            ['person', random.random()],
        ], columns=["class", "acc"])

        # Initialize a W&B run and log the bar plot
        with wandb.init(...) as run:
            bar_plot = wandb.plot.bar(
                table=table,
                label="class",
                value="acc",
                title="My Bar Plot",
            )
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
