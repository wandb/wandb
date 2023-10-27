import typing as t
from collections.abc import Iterable

import wandb


def line_series(
    xs: t.Union[t.Iterable, t.Iterable[t.Iterable]],
    ys: t.Iterable[t.Iterable],
    keys: t.Optional[t.Iterable] = None,
    title: t.Optional[str] = None,
    xname: t.Optional[str] = None,
    split_table: t.Optional[bool] = False,
):
    """Construct a line series plot.

    Arguments:
        xs (array of arrays, or array): Array of arrays of x values
        ys (array of arrays): Array of y values
        keys (array): Array of labels for the line plots
        title (string): Plot title.
        xname: Title of x-axis
        split_table (bool): If True, adds "Custom Chart Tables/" to the key of the table so that it's logged in a different section.

    Returns:
        A plot object, to be passed to wandb.log()

    Example:
        When logging a singular array for xs, all ys are plotted against that xs
        <!--yeadoc-test:plot-line-series-single-->
        ```python
        import wandb

        run = wandb.init()
        xs = [i for i in range(10)]
        ys = [[i for i in range(10)], [i**2 for i in range(10)]]
        run.log(
            {"line-series-plot1": wandb.plot.line_series(xs, ys, title="title", xname="step")}
        )
        run.finish()
        ```
        xs can also contain an array of arrays for having different steps for each metric
        <!--yeadoc-test:plot-line-series-double-->
        ```python
        import wandb

        run = wandb.init()
        xs = [[i for i in range(10)], [2 * i for i in range(10)]]
        ys = [[i for i in range(10)], [i**2 for i in range(10)]]
        run.log(
            {"line-series-plot2": wandb.plot.line_series(xs, ys, title="title", xname="step")}
        )
        run.finish()
        ```
    """
    if not isinstance(xs, Iterable):
        raise TypeError(f"Expected xs to be an array instead got {type(xs)}")

    if not isinstance(ys, Iterable):
        raise TypeError(f"Expected ys to be an array instead got {type(xs)}")

    for y in ys:
        if not isinstance(y, Iterable):
            raise TypeError(
                f"Expected ys to be an array of arrays instead got {type(y)}"
            )

    if not isinstance(xs[0], Iterable) or isinstance(xs[0], (str, bytes)):
        xs = [xs for _ in range(len(ys))]
    assert len(xs) == len(ys), "Number of x-lines and y-lines must match"

    if keys is not None:
        assert len(keys) == len(ys), "Number of keys and y-lines must match"
    data = [
        [x, f"key_{i}" if keys is None else keys[i], y]
        for i, (xx, yy) in enumerate(zip(xs, ys))
        for x, y in zip(xx, yy)
    ]

    table = wandb.Table(data=data, columns=["step", "lineKey", "lineVal"])

    return wandb.plot_table(
        "wandb/lineseries/v0",
        table,
        {"step": "step", "lineKey": "lineKey", "lineVal": "lineVal"},
        {"title": title, "xname": xname or "x"},
        split_table=split_table,
    )
