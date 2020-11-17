import wandb


def histogram(table, value, title=None):
    """
    Construct a histogram plot.

    Arguments:
        table (wandb.Table): Table of data.
        label (string): Name of column to use as data for bucketing.
        title (string): Plot title.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]
        table = wandb.Table(data=data, columns=["step", "height"])
        wandb.log({'histogram-plot1': wandb.plot.histogram(table, "height")})
        ```
    """
    return wandb.plot_table(
        "wandb/histogram/v0", table, {"value": value}, {"title": title}
    )
