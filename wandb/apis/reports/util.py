from abc import ABC
from collections import UserList
from typing import *

from .validators import *

UNDEFINED_TYPE = object()
NOT_SETABLE = None
NOT_DELABLE = None


def generate_name(length=12):
    # This implementation roughly based this snippet in core
    # https://github.com/wandb/core/blob/master/lib/js/cg/src/utils/string.ts#L39-L44

    import numpy as np

    rand = np.random.random()
    rand = int(str(rand)[2:])
    rand36 = np.base_repr(rand, 36)
    return rand36.lower()[:length]


def is_none(x):
    if isinstance(x, (list, tuple)):
        return all(v is None for v in x)
    else:
        return x is None or x == {}


class SubclassOnlyABC(ABC):
    def __new__(cls, *args, **kwargs):
        if cls.__bases__ == (SubclassOnlyABC,):
            raise TypeError(f"Abstract class {cls.__name__} cannot be instantiated")

        return super(SubclassOnlyABC, cls).__new__(cls)


def base_fget(self, instance):
    return instance.__dict__[self.name]


def base_fset(self, instance, value):
    instance.__dict__[self.name] = value


class Attr:
    """
    Like property, but with validators and optionally types.
    """

    def __init__(
        self,
        attr_type=UNDEFINED_TYPE,
        fget: callable = base_fget,
        fset: callable = base_fset,
        fdel: callable = None,
        doc: str = None,
        validators: List[callable] = [],
    ):
        self.attr_type = attr_type
        self.fget = fget
        self.fset = fset
        self.fdel = fdel
        if not isinstance(validators, list):
            validators = [validators]
        self.validators = validators  # + [type_validate]
        if self.attr_type is not UNDEFINED_TYPE:
            self.validators = [type_validate(attr_type)] + self.validators
        if doc is None and fget is not None:
            doc = fget.__doc__
        self.__doc__ = doc

    def __get__(self, instance, owner):
        if not instance:
            return self
        return self.fget(self, instance)

    def __set__(self, instance, value):
        if self.fset is None:
            raise AttributeError("Unsettable attr")
        self._validate(value)
        return self.fset(self, instance, value)

    def __delete__(self, instance):
        if self.fdel is None:
            raise AttributeError("Undeletable attr")
        return self.fdel(self, instance)

    def __set_name__(self, owner, name):
        self.name = name

    def _validate(self, value):
        for validator in self.validators:
            validator(self, value)


def sort_layouts(l):
    x = l["x"] + l["w"]
    y = l["y"] + l["h"]
    return y, x


def sort_panels_by_layout(panels):
    return sorted(panels, key=lambda p: sort_layouts(p.layout))


class CollapsingList(UserList):
    def __repr__(self):
        if len(self) > 2:
            items = self[:2]
            ending = ", ..."
        else:
            items = self
            ending = ""
        return "[{}{}]".format(", ".join(repr(i) for i in items), ending)
