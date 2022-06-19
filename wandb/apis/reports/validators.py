from abc import ABC, abstractmethod
from typing import Union

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


class Validator(ABC):
    def __init__(self, how=None):
        self.how = how

    @abstractmethod
    def call(self, attr_name, value):
        pass

    def __call__(self, attr, value):
        if value is None:
            return

        attr_name = attr._name.__repr__()
        if self.how == "keys":
            attr_name += " keys"
            for v in value:
                self.call(attr_name, v)
        elif self.how == "values":
            attr_name += " values"
            for v in value.values():
                self.call(attr_name, v)
        else:
            attr_name += " object"
            self.call(attr_name, value)


class TypeValidator(Validator):
    def __init__(self, attr_type, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            origin = attr_type.__origin__
            subtypes = attr_type.__args__
        except AttributeError:  # normal types
            self.attr_type = attr_type
        else:
            if origin is Union:
                self.attr_type = subtypes
            else:
                raise TypeError(f"{attr_type} is not currently supported.")
        self.attr_type = (self.attr_type, type(None))

    def call(self, attr_name, value):
        if not isinstance(value, self.attr_type):
            raise TypeError(
                f"{attr_name} must be of type {self.attr_type!r} (got {type(value)!r})"
            )


class OneOf(Validator):
    def __init__(self, options, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = (*options, None)

    def call(self, attr_name, value):
        if value not in self.options:
            raise ValueError(
                f"{attr_name} must be one of {self.options!r} (got {value!r})"
            )


class Length(Validator):
    def __init__(self, k, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.k = k

    def call(self, attr_name, value):
        if len(value) != self.k:
            raise ValueError(
                f"{attr_name} must have exactly {self.k} elements (got {len(value)!r}, elems: {value!r})"
            )


class Between(Validator):
    def __init__(self, lb, ub, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lb = lb
        self.ub = ub

    def call(self, attr_name, value):
        if not self.lb <= value <= self.ub:
            raise ValueError(
                f"{attr_name} must be between [{self.lb}, {self.ub}] inclusive (got {value})"
            )


class OrderString(TypeValidator):
    def call(self, attr_name, value):
        super().call(attr_name, value)

        if value[0] not in {"+", "-"}:
            raise ValueError(
                f'{attr_name} must be prefixed with "+" or "-" to indicate ascending or descending order'
            )
