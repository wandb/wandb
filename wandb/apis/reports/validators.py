LINEPLOT_STYLES = ["line", "stacked-area", "pct-area"]
BARPLOT_STYLES = ["bar", "boxplot", "violin"]
FONT_SIZES = ["small", "medium", "large", "auto"]
LEGEND_POSITIONS = ["north", "south", "east", "west"]
LEGEND_ORIENTATIONS = ["horizontal", "vertical"]
AGGFUNCS = ["mean", "min", "max", "median", "sum", "samples"]
RANGEFUNCS = ["minmax", "stddev", "stderr", "none", "samples"]
MARKS = ["solid", "dashed", "dotted", "dotdash", "dotdotdash"]
TIMESTEPS = ["seconds", "minutes", "hours", "days"]
SMOOTHING_TYPES = ["exponential", "gaussian", "average", "none"]


def type_validate(attr, value):
    if isinstance(value, (list, tuple)):
        for v in value:
            type_validate(attr, v)
    if not isinstance(value, attr.type):
        raise TypeError(
            f"{attr.name!r} values must be of type {attr.type!r} (got {type(value)!r})"
        )


def options(*opts):
    def _options(attr, value):
        if value not in opts:
            raise ValueError(
                f"{attr.name!r} must be one of {opts!r} (got {type(value)!r})"
            )

    return _options
