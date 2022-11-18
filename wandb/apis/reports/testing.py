from typing import (
    Any,
    Callable,
    Generic,
    Iterator,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    cast,
    get_type_hints,
)

from .util import Base, TypeValidator, Validator

T = TypeVar("T")
G = TypeVar("G")
# https://github.com/python/mypy/pull/2266

UNDEFINED_TYPE = TypeVar("UNDEFINED_TYPE")


def nested_get(json: Any, keys: str) -> Any:
    """
    Given a nested JSON dict and path, get the element at the terminal node.
    The first item of the path can be an object
    """
    path = keys.split(".")
    if len(path) == 1:
        return vars(json)[path[0]]
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


def nested_set(json: Any, keys: str, value: Any) -> None:
    """
    Given a nested JSON dict and path, set the element at the terminal node.
    The first item of the path can be an object.

    If nodes do not exist, they are created along the way.
    """
    path = keys.split(".")
    if len(path) == 1:
        vars(json)[path[0]] = value
    else:
        for key in keys[:-1]:
            if isinstance(json, Base):
                if not hasattr(json, key):
                    setattr(json, key, {})
                json = getattr(json, key)
            else:
                json = json.setdefault(key, {})
        json[keys[-1]] = value


class Property(Generic[T, G]):
    """Property descriptor with a default getter and setter."""

    def __init__(
        self,
        fget: Optional[Callable[[T], G]] = None,
        fset: Optional[Callable[[T, G], None]] = None,
    ) -> None:
        self.fget = fget or self.default_fget
        self.fset = fset or self.default_fset
        self.name = ""

    def __set_name__(self, owner: Any, name: str) -> None:
        self.name = name

    def __get__(
        self, obj: Optional[T], objtype: Optional[Type[T]] = None
    ) -> Union[G, "Property"]:
        if obj is None:
            return self
        if self.fget is None:
            raise AttributeError(f"unreadable attribute {self.name}")
        return self.fget(obj)

    def __set__(self, obj: T, value: G) -> None:
        if self.fset is None:
            raise AttributeError(f"can't set attribute {self.name}")
        self.fset(obj, value)

    def getter(self, fget: Callable[[T], G]) -> "Property":
        prop = type(self)(fget, self.fset)
        prop.name = self.name
        return prop

    def setter(self, fset: Callable[[T, G], None]) -> "Property":
        prop = type(self)(self.fget, fset)
        prop.name = self.name
        return prop

    def default_fget(self, obj: T) -> G:
        return obj.__dict__[self.name]

    def default_fset(self, obj: T, value: G) -> None:
        obj.__dict__[self.name] = value


class Validated(Property[T, G]):
    def __init__(
        self,
        # *args: Any,
        fget: Optional[Callable[[T], G]] = None,
        fset: Optional[Callable[[T, G], None]] = None,
        validators: Optional[List[Validator]] = None,
        # **kwargs: Any,
    ) -> None:
        # super().__init__(*args, **kwargs)
        super().__init__()
        if validators is None:
            validators = []
        self.validators = validators

    def __set__(self, obj: T, value: G) -> None:
        if not isinstance(value, type(self)):
            for validator in self.validators:
                validator(self, value)
        super().__set__(obj, cast(G, value))


class Typed(Validated[T, G]):
    def __set_name__(self, owner: Any, name: str) -> None:
        super().__set_name__(owner, name)
        self.type = get_type_hints(owner).get(name, UNDEFINED_TYPE)

        if self.type is not UNDEFINED_TYPE:
            self.validators = [TypeValidator(attr_type=self.type)] + self.validators


class JSONLinked(Property[T, G]):
    """Property that is linked to one or more JSON keys."""

    def __init__(
        self,
        *args: Any,
        json_path: Optional[Union[str, List[str]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.path_or_name = json_path

    def __set_name__(self, owner: Any, name: str) -> None:
        if self.path_or_name is None:
            self.path_or_name = name
        super().__set_name__(owner, name)

    def getter(self, fget: Callable[[T], G]) -> "Property":
        prop = type(self)(fget, self.fset, json_path=self.path_or_name)
        prop.name = self.name
        return prop

    def setter(self, fset: Callable[[T, G], None]) -> "Property":
        prop = type(self)(self.fget, fset, json_path=self.path_or_name)
        prop.name = self.name
        return prop

    def default_fget(self, obj: T) -> Union[G, List[G]]:
        if isinstance(self.path_or_name, str):
            return nested_get(obj, self.path_or_name)
        elif isinstance(self.path_or_name, list):
            return [nested_get(obj, p) for p in self.path_or_name]
        else:
            raise TypeError(f"Unexpected type for path {type(self.path_or_name)!r}")

    def default_fset(self, obj: T, value: Iterator[G]) -> None:
        if isinstance(self.path_or_name, str):
            nested_set(obj, self.path_or_name, value)
        elif isinstance(self.path_or_name, list):
            for p, v in zip(self.path_or_name, value):
                nested_set(obj, p, v)
        else:
            raise TypeError(f"Unexpected type for path {type(self.path_or_name)!r}")


class Attr(JSONLinked[T, G], Typed[T, G]):
    def getter(self, fget: Callable[[T], G]) -> "Property":
        prop = type(self)(
            fget, self.fset, json_path=self.path_or_name, validators=self.validators
        )
        prop.name = self.name
        return prop

    def setter(self, fset: Callable[[T, G], None]) -> "Property":
        prop = type(self)(
            self.fget, fset, json_path=self.path_or_name, validators=self.validators
        )
        prop.name = self.name
        return prop


class Something:
    a = Property()
