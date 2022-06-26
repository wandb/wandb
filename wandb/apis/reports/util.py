import dataclasses
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, TypeVar, overload

import wandb

from .validators import UNDEFINED_TYPE, LayoutDict, TypeValidator


class SubclassOnlyABC:
    def __new__(cls, *args, **kwargs):
        if SubclassOnlyABC in cls.__bases__:
            raise TypeError(f"Abstract class {cls.__name__} cannot be instantiated")

        return super().__new__(cls)


def is_none(x: Any):
    if isinstance(x, (list, tuple)):
        return all(v is None for v in x)
    return x is None or x == {}


class ShortReprMixin:
    def __repr__(self):
        clas = self.__class__.__name__
        props = {
            k: getattr(self, k)
            for k, v in self.__class__.__dict__.items()
            if isinstance(v, property) and type(v) is not property
        }
        settings = [f"{k}={v!r}" for k, v in props.items() if not is_none(v)]
        return "{}({})".format(clas, ", ".join(settings))


def nested_get(json: dict, keys: str) -> Any:
    """
    Given a nested JSON dict and path, get the element at the terminal node.
    The first item of the path can be an object
    """
    keys = keys.split(".")
    if len(keys) == 1:
        return vars(json)[keys[0]]
    else:
        rv = json
        for key in keys:
            if isinstance(rv, Base):
                if not hasattr(rv, key):
                    setattr(rv, key, {})
                rv = getattr(rv, key)
            else:
                if key not in rv:
                    rv[key] = None
                rv = rv[key]
        return rv


def nested_set(json: dict, keys: str, value: Any) -> None:
    """
    Given a nested JSON dict and path, set the element at the terminal node.
    The first item of the path can be an object.

    If nodes do not exist, they are created along the way.
    """
    keys = keys.split(".")
    if len(keys) == 1:
        vars(json)[keys[0]] = value
    else:
        for key in keys[:-1]:
            if isinstance(json, Base):
                if not hasattr(json, key):
                    setattr(json, key, {})
                json = getattr(json, key)
            else:
                json = json.setdefault(key, {})
        json[keys[-1]] = value


Func = TypeVar("Func", bound=Callable)


class Attr:
    def __init__(self, field: dataclasses.Field):
        self.field = field
        self.fget: Optional[Callable] = None
        self.fset: Optional[Callable] = None

    def __call__(self, func: Func) -> Func:
        return self.getter(func)

    def getter(self, func: Func) -> Func:
        self.fget = func
        return func

    def setter(self, func: Func) -> Func:
        field = self.field

        def wrapper(owner, value):
            validators = field.metadata.get("validators", [])
            validators = [TypeValidator(field.type)] + validators

            for validator in validators:
                validator(field.name, value)
            return func(owner, value)

        self.fset = wrapper
        return wrapper

    def __set_name__(self, owner, name):
        field = self.field
        path_or_name = field.metadata.get("json_path", name)

        self.type = owner.__annotations__.get(name, UNDEFINED_TYPE)
        if self.fget is None:

            def _fget(self):
                if isinstance(path_or_name, str):
                    return nested_get(self, path_or_name)
                elif isinstance(path_or_name, list):
                    return [nested_get(self, p) for p in path_or_name]
                else:
                    raise TypeError(f"Unexpected type for path {type(path_or_name)!r}")

            self.fget = self.getter(_fget)
        if self.fset is None:

            def fset(self, value):
                def _fset(self, value):
                    if isinstance(path_or_name, str):
                        nested_set(self, path_or_name, value)
                    elif isinstance(path_or_name, list):
                        for p, v in zip(path_or_name, value):
                            nested_set(self, p, v)
                    else:
                        raise TypeError(
                            f"Unexpected type for path {type(path_or_name)!r}"
                        )

                setattr(owner, field.name, getattr(owner, field.name).setter(_fset))
                setattr(self, field.name, value)

            self.fset = self.setter(fset)

        class Property(property):
            if field.default is not dataclasses.MISSING:
                _default_factory = lambda default=field.default: default
            elif field.default_factory is not dataclasses.MISSING:
                _default_factory = field.default_factory
            else:

                def _default_factory():
                    raise TypeError(
                        f"{owner.__name__}.__init__() missing parameter {field.name!r}"
                    )

            def setter(self, fset: Callable[[Any, Any], None]) -> "Property":
                def handle_property_default(self, value):
                    if isinstance(value, property):
                        if Property._default_factory is None:
                            raise TypeError(f"Missing parameter {field.name!r}")
                        else:
                            value = Property._default_factory()
                    fset(self, value)

                return super().setter(handle_property_default)

        self.field.default = Property(self.fget).setter(self.fset)
        self.field.default_factory = dataclasses.MISSING
        setattr(owner, name, field)


@overload
def attr(
    *,
    default: Any = ...,
    default_factory: Callable[[], Any] = None,
    init=True,
    repr=True,
    hash=None,
    compare=True,
    metadata: Mapping = None,
) -> Any:
    ...


@overload
def attr(field: Any) -> Attr:
    ...


def attr(field=None, **kwargs):
    """
    Similar to and accepts arguments for `dataclasses.field`.

    Also behaves like:
        - `property`, with getters and setters applied by default (overwritable)
        - validation (includig automatic type validation) via metadata["validators"]
        - JSON mapping via metadata["json_path"]
    """
    if field is None:
        return Attr(dataclasses.field(**kwargs))
    elif not isinstance(field, Attr):
        raise ValueError(f"Invalid field property {field}")
    else:
        return field


class Base(SubclassOnlyABC, ShortReprMixin):
    """
    Base for most objects in the Report API.
    Adds helpers for working with the `attr` function, including:
        - Retrieving JSON paths
        - Cleaning up function signatures
    """

    # We use `new` instead of `init`, otherwise the dataclass init becomes noisy.
    def __new__(cls, *args, **kwargs):
        if hasattr(cls, "_"):  # hide getter/setter func
            delattr(cls, "_")
        obj = super().__new__(cls, *args, **kwargs)
        obj._spec = dict()
        return obj

    def __post_init__(self):
        self.update_sig()
        pass

    @classmethod
    def from_json(cls, spec):
        obj = cls()
        obj._spec = spec
        return obj

    def update_sig(self):
        """
        Overwrite function signatures to make them easier to read by removing noisy Property reprs
        """
        sig = inspect.signature(self.__class__)
        new_params = [
            inspect.Parameter(
                v.name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=v.annotation,
            )
            for v in sig.parameters.values()
            if not v.name.startswith("_")
        ]
        new_sig = sig.replace(parameters=new_params)
        setattr(self.__class__, "__signature__", new_sig)
        # setattr(self.__class__, '__doc__', str(new_sig))

    def _get_path(self, var):
        """
        Helper function to get the json path for a variable
        """
        return type(self).__dataclass_fields__[var].metadata["json_path"]

    @property
    def spec(self):
        return self._spec


def _default_panel_layout():
    return {"x": 0, "y": 0, "w": 8, "h": 6}


@dataclass(repr=False)
class Panel(Base, ABC):
    """
    ABC for Panels.
    All panels must inherit from this.
    """

    layout: dict = attr(
        default_factory=_default_panel_layout,
        metadata={"json_path": "spec.layout", "validators": [LayoutDict()]},
    )

    # We use `new` instead of `init`, otherwise the dataclass init becomes noisy.
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls, *args, **kwargs)
        obj._spec["viewType"] = obj.view_type
        obj.panel_metrics_helper = wandb.apis.public.PanelMetricsHelper()
        return obj

    @classmethod
    def from_json(cls, spec):
        # obj = super().__new__(cls)
        obj = cls()
        obj._spec = spec
        return obj

    @property
    @abstractmethod
    def view_type(self):
        return "UNKNOWN PANEL"

    @property
    def config(self):
        return self._spec["config"]


class Block(Base, SubclassOnlyABC):
    """
    ABC for Blocks.
    All blocks must inherit from this.
    """

    @classmethod
    def from_json(cls, spec):
        obj = cls()
        obj._spec = spec
        return obj


def generate_name(length: int = 12) -> str:
    """
    Generate random name.
    This implementation roughly based the following snippet in core:
    https://github.com/wandb/core/blob/master/lib/js/cg/src/utils/string.ts#L39-L44
    """

    import numpy as np

    rand = np.random.random()
    rand = int(float(str(rand)[2:]))
    rand36 = np.base_repr(rand, 36)
    return rand36.lower()[:length]


def _(x):
    """
    Identity function hack for decorators.
    This can be removed in py39 when decorators support more flexible grammar
    https://peps.python.org/pep-0614/

    Attr usage today:
        @_(attr(blocks).getter)
        def _(self):
            ...

    Attr usage in py39:
        @attr(blocks).getter
        def _(self):
            ...
    """
    return x


def tuple_factory(value=None, size=1):
    def _tuple_factory():
        return tuple(value for _ in range(size))

    return _tuple_factory
