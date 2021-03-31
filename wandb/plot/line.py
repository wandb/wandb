import wandb


def line(table, x, y, stroke=None, title=None):
    """
    Construct a line plot.

    Arguments:
        table (wandb.Table): Table of data.
        x (string): Name of column to as for x-axis values.
        y (string): Name of column to as for y-axis values.
        stroke (string): Name of column to map to the line stroke scale.
        title (string): Plot title.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]
        table = wandb.Table(data=data, columns=["step", "height"])
        wandb.log({'line-plot1': wandb.plot.line(table, "step", "height")})
        ```
    """
    return wandb.plot_table(
        "wandb/line/v0", table, {"x": x, "y": y, "stroke": stroke}, {"title": title}
    )
