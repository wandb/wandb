import wandb


def line_series(x, ys, title, xname=None):
    """
    Construct a line series plot.

    Arguments:
        x (array): Array of x values
        ys (array of dicts of {key: array}): Array of dictionaries with line names and values
        title (string): Plot title.
        xname: Title of x-axis

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        x = [i for i in range(1,10)]
        ys = {
            "y1": [i for i in range(1,10)],
            "y2": [i**2 for i in range(1,10)]
        }
        wandb.log({'line-series-plot1': wandb.plot.line_series(x, ys, "title", "step")})
        ```
    """

    for _, value in ys.items():
        assert len(value) == len(x), "All y arrays must match with length of x"

    data = []
    for i in range(len(x)):
        for key in ys.keys():
            data.append([x[i], key, ys[key][i]])

    table = wandb.Table(data=data, columns=["step", "lineKey", "lineVal"])

    return wandb.plot_table(
        "wandb/lineseries/v0",
        table,
        {"step": "step", "lineKey": "lineKey", "lineVal": "lineVal"},
        {"title": title, "xname": xname or "x"},
    )
