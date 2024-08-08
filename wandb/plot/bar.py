from typing import Optional

import wandb


def bar(
    table: wandb.Table,
    label: str,
    value: str,
    title: Optional[str] = None,
    split_table: Optional[bool] = False,
):
    """Construct a bar plot.

    Arguments:
        table (wandb.Table): Table of data.
        label (string): Name of column to use as each bar's label.
        value (string): Name of column to use as each bar's value.
        title (string): Plot title.
        split_table (bool): If True, adds "Custom Chart Tables/" to the key of the table so that it's logged in a different section.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        table = wandb.Table(data=[
            ['car', random.random()],
            ['bus', random.random()],
            ['road', random.random()],
            ['person', random.random()],
            ], columns=["class", "acc"])
        wandb.log({'bar-plot1': wandb.plot.bar(table, "class", "acc")})
        ```
    """
    return wandb.plot_table(
        "wandb/bar/v0",
        table,
        {"label": label, "value": value},
        {"title": title},
        split_table=split_table,
    )
