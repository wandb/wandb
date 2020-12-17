from six.moves.collections_abc import Sequence
import wandb


def line_series(xs, ys, keys=None, title=None, xname=None):
    """
    Construct a line series plot.

    Arguments:
        xs (array of arrays, or array): Array of arrays of x values
        ys (array of arrays): Array of y values
        title (string): Plot title.
        xname: Title of x-axis

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        ```
        When logging a singular array for x, all ys are plotted against that x
        x = [i for i in range(10)]
        ys = [
            [i for i in range(10)],
            [i**2 for i in range(10)]
        ]
        wandb.log({'line-series-plot1': wandb.plot.line_series(x, ys, "title", "step")})

        xs can also contain an array of arrays for having different steps for each metric
        xs = [[i for i in range(10)], [2*i for i in range(10)]]
        ys = [
            [i for i in range(10)],
            [i**2 for i in range(10)]
        ]
        wandb.log({'line-series-plot1': wandb.plot.line_series(xs, ys, "title", "step")})
        ```
    """
    data = []
    if not isinstance(xs[0], Sequence):
        xs = [xs for _ in range(len(ys))]
    assert len(xs) == len(ys), "Number of x-lines and y-lines must match"
    for i, series in enumerate([list(zip(xs[i], ys[i])) for i in range(len(xs))]):
        for x, y in series:
            if keys is None:
                key = "key_{}".format(i)
            else:
                key = keys[i]
            data.append([x, key, y])

    table = wandb.Table(data=data, columns=["step", "lineKey", "lineVal"])

    return wandb.plot_table(
        "wandb/lineseries/v0",
        table,
        {"step": "step", "lineKey": "lineKey", "lineVal": "lineVal"},
        {"title": title, "xname": xname or "x"},
    )
