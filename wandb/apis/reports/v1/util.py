import random
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
    get_type_hints,
)

from ...public import PanelMetricsHelper
from .validators import UNDEFINED_TYPE, TypeValidator, Validator

# Func = TypeVar("Func")
T = TypeVar("T")
V = TypeVar("V")
Func = Callable[[T], V]


def generate_name(length: int = 12) -> str:
    """Generate a random name.

    This implementation roughly based the following snippet in core:
    https://github.com/wandb/core/blob/master/lib/js/cg/src/utils/string.ts#L39-L44.
    """

    # Borrowed from numpy: https://github.com/numpy/numpy/blob/v1.23.0/numpy/core/numeric.py#L2069-L2123
    def base_repr(number: int, base: int, padding: int = 0) -> str:
        digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if base > len(digits):
            raise ValueError("Bases greater than 36 not handled in base_repr.")
        elif base < 2:
            raise ValueError("Bases less than 2 not handled in base_repr.")

        num = abs(number)
        res = []
        while num:
            res.append(digits[num % base])
            num //= base
        if padding:
            res.append("0" * padding)
        if number < 0:
            res.append("-")
        return "".join(reversed(res or "0"))

    rand = random.random()
    rand = int(float(str(rand)[2:]))
    rand36 = base_repr(rand, 36)
    return rand36.lower()[:length]


def coalesce(*arg: Any) -> Any:
    """Return the first non-none value in the list of arguments.

    Similar to ?? in C#.
    """
    return next((a for a in arg if a is not None), None)


def nested_get(json: dict, keys: str) -> Any:
    """Get the element at the terminal node of a nested JSON dict based on `path`.

    The first item of the path can be an object.
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
    """Set the element at the terminal node of a nested JSON dict based on `path`.

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


class Property(Generic[T]):
    """Property descriptor with a default getter and setter."""

    def __init__(
        self, fget: Optional[Func] = None, fset: Optional[Func] = None
    ) -> None:
        self.fget = fget or self.default_fget
        self.fset = fset or self.default_fset
        self.name = ""

    def __set_name__(self, owner: Any, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, objtype: Optional[Any] = None) -> T:
        if obj is None:
            return self
        if self.fget is None:
            raise AttributeError(f"unreadable attribute {self.name}")
        return self.fget(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        if self.fset is None:
            raise AttributeError(f"can't set attribute {self.name}")
        self.fset(obj, value)

    def getter(self, fget: Func) -> Func:
        prop = type(self)(fget, self.fset)
        prop.name = self.name
        return prop

    def setter(self, fset: Func) -> Func:
        prop = type(self)(self.fget, fset)
        prop.name = self.name
        return prop

    def default_fget(self, obj: Any) -> Any:
        return obj.__dict__[self.name]

    def default_fset(self, obj: Any, value: Any) -> None:
        obj.__dict__[self.name] = value


class Validated(Property):
    def __init__(
        self, *args: Func, validators: Optional[List[Validator]] = None, **kwargs: Func
    ) -> None:
        super().__init__(*args, **kwargs)
        if validators is None:
            validators = []
        self.validators = validators

    def __set__(self, instance: Any, value: Any) -> None:
        if not isinstance(value, type(self)):
            for validator in self.validators:
                validator(self, value)
        super().__set__(instance, value)


class Typed(Validated):
    def __set_name__(self, owner: Any, name: str) -> None:
        super().__set_name__(owner, name)
        self.type = get_type_hints(owner).get(name, UNDEFINED_TYPE)

        if self.type is not UNDEFINED_TYPE:
            self.validators = [TypeValidator(attr_type=self.type)] + self.validators


class JSONLinked(Property):
    """Property that is linked to one or more JSON keys."""

    def __init__(
        self,
        *args: Func,
        json_path: Optional[Union[str, List[str]]] = None,
        **kwargs: Func,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.path_or_name = json_path

    def __set_name__(self, owner: Any, name: str) -> None:
        if self.path_or_name is None:
            self.path_or_name = name
        super().__set_name__(owner, name)

    def getter(self, fget: Func) -> Func:
        prop = type(self)(fget, self.fset, json_path=self.path_or_name)
        prop.name = self.name
        return prop

    def setter(self, fset: Func) -> Func:
        prop = type(self)(self.fget, fset, json_path=self.path_or_name)
        prop.name = self.name
        return prop

    def default_fget(self, obj: Any) -> Union[Any, List[Any]]:
        if isinstance(self.path_or_name, str):
            return nested_get(obj, self.path_or_name)
        elif isinstance(self.path_or_name, list):
            return [nested_get(obj, p) for p in self.path_or_name]
        else:
            raise TypeError(f"Unexpected type for path {type(self.path_or_name)!r}")

    def default_fset(self, obj: Any, value: Any) -> None:
        if isinstance(self.path_or_name, str):
            nested_set(obj, self.path_or_name, value)
        elif isinstance(self.path_or_name, list):
            for p, v in zip(self.path_or_name, value):
                nested_set(obj, p, v)
        else:
            raise TypeError(f"Unexpected type for path {type(self.path_or_name)!r}")


class Attr(Typed, JSONLinked):
    def getter(self, fget: Func) -> Func:
        prop = type(self)(
            fget, self.fset, json_path=self.path_or_name, validators=self.validators
        )
        prop.name = self.name
        return prop

    def setter(self, fset: Func) -> Func:
        prop = type(self)(
            self.fget, fset, json_path=self.path_or_name, validators=self.validators
        )
        prop.name = self.name
        return prop


class SubclassOnlyABC:
    def __new__(cls, *args: Any, **kwargs: Any) -> T:
        if SubclassOnlyABC in cls.__bases__:
            raise TypeError(f"Abstract class {cls.__name__} cannot be instantiated")

        return super().__new__(cls)


class ShortReprMixin:
    def __repr__(self) -> str:
        clas = self.__class__.__name__
        props = {
            k: getattr(self, k)
            for k, v in self.__class__.__dict__.items()
            if isinstance(v, Attr)
        }
        settings = [
            f"{k}={v!r}" for k, v in props.items() if not self._is_interesting(v)
        ]
        return "{}({})".format(clas, ", ".join(settings))

    @staticmethod
    def _is_interesting(x: Any) -> bool:
        if isinstance(x, (list, tuple)):
            return all(v is None for v in x)
        return x is None or x == {}


class Base(SubclassOnlyABC, ShortReprMixin):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._spec = {}

    @property
    def spec(self) -> Dict[str, Any]:
        return self._spec

    @classmethod
    def from_json(cls, spec: Dict[str, Any]) -> T:
        obj = cls()
        obj._spec = spec
        return obj

    def _get_path(self, var: str) -> str:
        return vars(type(self))[var].path_or_name


class Panel(Base, SubclassOnlyABC):
    layout: dict = Attr(json_path="spec.layout")

    def __init__(
        self, layout: Optional[Dict[str, int]] = None, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._spec["viewType"] = self.view_type
        self._spec["__id__"] = generate_name()
        self.layout = coalesce(layout, self._default_panel_layout())
        self.panel_metrics_helper = PanelMetricsHelper()

    @property
    def view_type(self) -> str:
        return "UNKNOWN PANEL"

    @property
    def config(self) -> Dict[str, Any]:
        return self._spec["config"]

    @staticmethod
    def _default_panel_layout() -> Dict[str, int]:
        return {"x": 0, "y": 0, "w": 8, "h": 6}

    @layout.setter
    def layout(self, d: Dict[str, int]) -> None:
        d["x"] = coalesce(d.get("x"), self._default_panel_layout()["x"])
        d["y"] = coalesce(d.get("y"), self._default_panel_layout()["y"])
        d["w"] = coalesce(d.get("w"), self._default_panel_layout()["w"])
        d["h"] = coalesce(d.get("h"), self._default_panel_layout()["h"])

        # json_path = self._get_path("layout")
        # can't use _get_path because it's not on the obj... if only we had dataclass...
        json_path = "spec.layout"
        nested_set(self, json_path, d)


class Block(Base, SubclassOnlyABC):
    pass


def fix_collisions(panels: List[Panel]) -> List[Panel]:
    x_max = 24

    for i, p1 in enumerate(panels):
        for p2 in panels[i:]:
            if collides(p1, p2):
                # try to move right
                x, y = shift(p1, p2)
                if p2.layout["x"] + p2.layout["w"] + x <= x_max:
                    p2.layout["x"] += x

                # if you hit right right bound, move down
                else:
                    p2.layout["y"] += y

                    # then check if you can move left again to cleanup layout
                    p2.layout["x"] = 0
    return panels


def collides(p1: Panel, p2: Panel) -> bool:
    l1, l2 = p1.layout, p2.layout

    if (
        (p1.spec["__id__"] == p2.spec["__id__"])
        or (l1["x"] + l1["w"] <= l2["x"])
        or (l1["x"] >= l2["w"] + l2["x"])
        or (l1["y"] + l1["h"] <= l2["y"])
        or (l1["y"] >= l2["y"] + l2["h"])
    ):
        return False

    return True


def shift(p1: Panel, p2: Panel) -> Tuple[Panel, Panel]:
    l1, l2 = p1.layout, p2.layout

    x = l1["x"] + l1["w"] - l2["x"]
    y = l1["y"] + l1["h"] - l2["y"]

    return x, y


class InlineLaTeX(Base):
    latex: str = Attr()

    def __init__(self, latex="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.latex = latex

    @property
    def spec(self) -> dict:
        return {"type": "latex", "children": [{"text": ""}], "content": self.latex}


class InlineCode(Base):
    code: str = Attr()

    def __init__(self, code="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.code = code

    @property
    def spec(self) -> dict:
        return {"text": self.code, "inlineCode": True}


class Link(Base):
    text: str = Attr()
    url: str = Attr()

    def __init__(self, text, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text
        self.url = url

    @property
    def spec(self) -> dict:
        return {"type": "link", "url": self.url, "children": [{"text": self.text}]}


def weave_inputs(spec):
    return spec["config"]["panelConfig"]["exp"]["fromOp"]["inputs"]
