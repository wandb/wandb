from abc import ABC, abstractmethod
from typing import TypeVar, Union

LINEPLOT_STYLES = ["line", "stacked-area", "pct-area", None]
BARPLOT_STYLES = ["bar", "boxplot", "violin", None]
FONT_SIZES = ["small", "medium", "large", "auto", None]
LEGEND_POSITIONS = ["north", "south", "east", "west", None]
LEGEND_ORIENTATIONS = ["horizontal", "vertical", None]
AGGFUNCS = ["mean", "min", "max", "median", "sum", "samples", None]
RANGEFUNCS = ["minmax", "stddev", "stderr", "none", "samples", None]
MARKS = ["solid", "dashed", "dotted", "dotdash", "dotdotdash", None]
TIMESTEPS = ["seconds", "minutes", "hours", "days", None]
SMOOTHING_TYPES = ["exponential", "gaussian", "average", "none", None]
CODE_COMPARE_DIFF = ["split", "unified", None]


UNDEFINED_TYPE = TypeVar("UNDEFINED_TYPE")


class Validator(ABC):
    def __init__(self, how=None):
        self.how = how

    @abstractmethod
    def call(self, attr_name, value):
        pass

    def __call__(self, attr, value):
        attr_name = attr.name
        if value is None and self.how in {"keys", "values"}:
            return
        if self.how == "keys":
            attr_name += " keys"
            for v in value:
                self.call(attr_name, v)
        elif self.how == "values":
            attr_name += " values"
            for v in value.values():
                self.call(attr_name, v)
        elif self.how is None:
            attr_name += " object"
            self.call(attr_name, value)
        else:
            raise ValueError(
                'Validator setting `how` must be one of ("keys", "values", None)'
            )


class TypeValidator(Validator):
    def __init__(self, attr_type, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attr_type = attr_type
        try:
            origin = attr_type.__origin__
            subtypes = attr_type.__args__
        except AttributeError:  # normal types
            self.attr_type = (attr_type,)
        else:
            if origin is Union:
                self.attr_type = subtypes
            else:
                raise TypeError(f"{attr_type} is not currently supported.")

    def call(self, attr_name, value):
        if not isinstance(value, self.attr_type):
            raise TypeError(
                f"{attr_name} must be of type {self.attr_type!r} (got {type(value)!r})"
            )


class OneOf(Validator):
    def __init__(self, options, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = options

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
    def __init__(self):
        super().__init__(attr_type=str)

    def call(self, attr_name, value):
        super().call(attr_name, value)

        if value[0] not in {"+", "-"}:
            raise ValueError(
                f'{attr_name} must be prefixed with "+" or "-" to indicate ascending or descending order'
            )


class LayoutDict(Validator):
    def call(self, attr_name, value):
        if set(value.keys()) != {"x", "y", "w", "h"}:
            raise ValueError(
                f"{attr_name} must be a dict containing exactly the keys `x`, y`, `w`, `h`"
            )
        for k, v in value.items():
            if not isinstance(v, int):
                raise ValueError(
                    f"{attr_name} key `{k}` must be of type {int} (got {type(v)!r})"
                )
