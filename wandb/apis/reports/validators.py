from collections.abc import Iterable
from functools import wraps

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
CODE_COMPARE_DIFF = ["split", "unified"]


def allow(option):
    def deco(validator):
        @wraps(validator)
        def wrapper(*args, **kwargs):
            args = [
                (*arg, option) if isinstance(arg, Iterable) else (arg, option)
                for arg in args
            ]
            return validator(*args, **kwargs)

        return wrapper

    return deco


@allow(type(None))
def type_validate(attr_type, how=None):
    def _type_validate(attr, value):
        for v in howify(value, how):
            if not isinstance(v, attr_type):
                raise TypeError(
                    f"{attr.name!r} values must be of type {attr_type!r} (got {type(v)!r})"
                )

    return _type_validate


@allow(None)
def one_of(opts, how=None):
    def _one_of(attr, value):
        for v in howify(value, how):
            if v not in opts:
                raise ValueError(f"{attr.name!r} must be one of {opts!r} (got {v!r})")

    return _one_of


def length(n):
    def _expected_len(attr, value):
        if len(value) > n:
            raise ValueError(
                f"{attr.name!r} must have a length of {n} (got len({attr.name!r})=={len(value)!r}"
            )

    return _expected_len


@allow(type(None))
def elem_types(attr_type, how=None):
    def _elements_of_type(attr, value):
        for v in howify(value, how):
            if not isinstance(v, attr_type):
                raise TypeError(
                    f"{attr.name!r} elements must be of type {attr_type!r} (got {type(v)!r})"
                )

    return _elements_of_type


def between(lb, ub, how=None):
    def _between(attr, value):
        for v in howify(value, how):
            if not lb <= v <= ub:
                raise ValueError(
                    f"{attr.name!r} values must be between ({lb}, {ub}) (got {v})"
                )

    return _between


def howify(value, how=None):
    if how == "keys":
        return value.keys()
    elif how == "values":
        return value.values()
    else:
        return (value,)


# def dict_values_between(lb, ub):
#     def _dict_values_between(attr, value):
#         for v in value.keys():
#             if not lb <= v <= ub:
#                 raise ValueError(
#                     f"{attr.name!r} dict values must be between ({lb}, {ub}) (got {value})"
#                 )

#     return _dict_values_between


# def dict_keys_types(attr_type):
#     def _dict_keys_of_type(attr, value):
#         if not isinstance(value, attr_type):
#             raise TypeError(
#                 f"{attr.name!r} dict keys must be of type {attr_type!r} (got {type(value)!r})"
#             )

#     return _dict_keys_of_type
