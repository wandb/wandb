import wandb


def scatter(table, x, y, title=None):
    """
    Construct a scatter plot.

    Arguments:
        table (wandb.Table): Table of data.
        x (string): Name of column to as for x-axis values.
        y (string): Name of column to as for y-axis values.
        title (string): Plot title.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]
        table = wandb.Table(data=data, columns=["step", "height"])
        wandb.log({'scatter-plot1': wandb.plot.scatter(table, "step", "height")})
        ```
    """
    return wandb.plot_table(
        "wandb/scatter/v0", table, {"x": x, "y": y}, {"title": title}
    )
