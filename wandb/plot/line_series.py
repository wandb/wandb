from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

import wandb
from wandb.plot.custom_chart import plot_table

if TYPE_CHECKING:
    from wandb.plot.custom_chart import CustomChart


def line_series(
    xs: Iterable[Iterable[Any]] | Iterable[Any],
    ys: Iterable[Iterable[Any]],
    keys: Iterable[str] | None = None,
    title: str = "",
    xname: str = "x",
    split_table: bool = False,
) -> CustomChart:
    """Constructs a line series chart.

    Args:
        xs (Iterable[Iterable] | Iterable): Sequence of x values. If a singular
            array is provided, all y values are plotted against that x array. If
            an array of arrays is provided, each y value is plotted against the
            corresponding x array.
        ys (Iterable[Iterable]): Sequence of y values, where each iterable represents
            a separate line series.
        keys (Iterable[str]): Sequence of keys for labeling each line series. If
            not provided, keys will be automatically generated as "line_1",
            "line_2", etc.
        title (str): Title of the chart.
        xname (str): Label for the x-axis.
        split_table (bool): Whether the table should be split into a separate section
            in the W&B UI. If `True`, the table will be displayed in a section named
            "Custom Chart Tables". Default is `False`.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass it to `wandb.log()`.

    Examples:
        1. Logging a single x array where all y series are plotted against
           the same x values:

        ```
        import wandb

        # Initialize W&B run
        with wandb.init(project="line_series_example") as run:
            # x values shared across all y series
            xs = list(range(10))

            # Multiple y series to plot
            ys = [
                [i for i in range(10)],  # y = x
                [i**2 for i in range(10)],  # y = x^2
                [i**3 for i in range(10)],  # y = x^3
            ]

            # Generate and log the line series chart
            line_series_chart = wandb.plot.line_series(
                xs,
                ys,
                title="title",
                xname="step",
            )
            run.log({"line-series-single-x": line_series_chart})
        ```

        In this example, a single `xs` series (shared x-values) is used for all
        `ys` series. This results in each y-series being plotted against the
        same x-values (0-9).

        2. Logging multiple x arrays where each y series is plotted against
           its corresponding x array:

        ```python
        import wandb

        # Initialize W&B run
        with wandb.init(project="line_series_example") as run:
            # Separate x values for each y series
            xs = [
                [i for i in range(10)],  # x for first series
                [2 * i for i in range(10)],  # x for second series (stretched)
                [3 * i for i in range(10)],  # x for third series (stretched more)
            ]

            # Corresponding y series
            ys = [
                [i for i in range(10)],  # y = x
                [i**2 for i in range(10)],  # y = x^2
                [i**3 for i in range(10)],  # y = x^3
            ]

            # Generate and log the line series chart
            line_series_chart = wandb.plot.line_series(
                xs, ys, title="Multiple X Arrays Example", xname="Step"
            )
            run.log({"line-series-multiple-x": line_series_chart})
        ```

        In this example, each y series is plotted against its own unique x series.
        This allows for more flexibility when the x values are not uniform across
        the data series.

        3. Customizing line labels using `keys`:

        ```python
        import wandb

        # Initialize W&B run
        with wandb.init(project="line_series_example") as run:
            xs = list(range(10))  # Single x array
            ys = [
                [i for i in range(10)],  # y = x
                [i**2 for i in range(10)],  # y = x^2
                [i**3 for i in range(10)],  # y = x^3
            ]

            # Custom labels for each line
            keys = ["Linear", "Quadratic", "Cubic"]

            # Generate and log the line series chart
            line_series_chart = wandb.plot.line_series(
                xs,
                ys,
                keys=keys,  # Custom keys (line labels)
                title="Custom Line Labels Example",
                xname="Step",
            )
            run.log({"line-series-custom-keys": line_series_chart})
        ```

        This example shows how to provide custom labels for the lines using
        the `keys` argument. The keys will appear in the legend as "Linear",
        "Quadratic", and "Cubic".

    """
    # If xs is a single array, repeat it for each y in ys
    if not isinstance(xs[0], Iterable) or isinstance(xs[0], (str, bytes)):
        xs = [xs] * len(ys)

    if len(xs) != len(ys):
        msg = f"Number of x-series ({len(xs)}) must match y-series ({len(ys)})."
        raise ValueError(msg)

    if keys is None:
        keys = [f"line_{i}" for i in range(len(ys))]

    if len(keys) != len(ys):
        msg = f"Number of keys ({len(keys)}) must match y-series ({len(ys)})."
        raise ValueError(msg)

    data = [
        [x, keys[i], y]
        for i, (xx, yy) in enumerate(zip(xs, ys))
        for x, y in zip(xx, yy)
    ]
    table = wandb.Table(
        data=data,
        columns=["step", "lineKey", "lineVal"],
    )

    return plot_table(
        data_table=table,
        vega_spec_name="wandb/lineseries/v0",
        fields={
            "step": "step",
            "lineKey": "lineKey",
            "lineVal": "lineVal",
        },
        string_fields={"title": title, "xname": xname},
        split_table=split_table,
    )
