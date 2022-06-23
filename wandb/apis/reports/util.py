from copy import deepcopy
from dataclasses import dataclass
import inspect
from typing import Any, List, Tuple

import wandb

from .validators import TypeValidator

UNDEFINED_TYPE = object()


class BaseMeta(type):
    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        for _, member in inspect.getmembers(cls):
            if not isinstance(member, Descriptor):
                continue
            member.assign_default_value(instance)
        return instance


class Descriptor:
    def __init__(self, fget=None, fset=None, default=None, default_factory=None):
        self.fget = fget or self.base_fget
        self.fset = fset or self.base_fset
        self._name = ""

        if default and default_factory:
            raise ValueError(
                "Must specify only one of `default` or `default_factory`, not both"
            )

        self.default = default
        self.default_factory = default_factory

    def __set_name__(self, owner, name):
        if type(owner) is not BaseMeta:
            raise TypeError(
                f"{owner.__name__}.{name} uses {self.__class__.__name__!r} but does not have metaclass {BaseMeta!r} (got ({type(owner)!r}))"
            )
        self._name = name

    def __get__(self, instance, owner=None):
        return self.fget(self, instance)

    def __set__(self, instance, value):
        self.fset(self, instance, value)

    def assign_default_value(self, instance):
        default = self.default_factory() if self.default_factory else self.default
        if not getattr(instance, self._name):
            setattr(instance, self._name, default)

    @staticmethod
    def base_fget(attr, instance):
        return instance.__dict__.get(attr._name)

    @staticmethod
    def base_fset(attr, instance, value):
        instance.__dict__[attr._name] = value


class NotRequired(Descriptor):
    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return super().__get__(instance, owner)

    def __set__(self, instance, value):
        if value is self:
            # self.assign_default_value(instance)
            value = getattr(instance, self._name)
        #     # value = self.default
        super().__set__(instance, value)


class Validated(Descriptor):
    def __init__(self, validators=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if validators is None:
            validators = []
        self.validators = validators

    def __set__(self, instance, value):
        if not isinstance(value, type(self)):
            for validator in self.validators:
                validator(self, value)
        super().__set__(instance, value)


class Typed(Validated):
    # a bit hacky, but cleaner in class def :)
    def __set_name__(self, owner, name):
        super().__set_name__(owner, name)
        self.type = owner.__annotations__.get(name, UNDEFINED_TYPE)

        if self.type is not UNDEFINED_TYPE:
            self.validators = [TypeValidator(self.type)] + self.validators


def find(json: dict, element: List[str]) -> Any:
    keys = element.split(".")
    rv = json
    for key in keys:
        if key not in rv:
            rv[key] = None
        rv = rv[key]
    return rv


def nested_set(json: dict, keys: str, value: Any) -> None:
    keys = keys.split(".")
    for key in keys[:-1]:
        json = json.setdefault(key, {})
    json[keys[-1]] = value


class JSONLinked(Descriptor):
    def __init__(self, path, *args, base_path="spec", **kwargs):
        super().__init__(*args, **kwargs)
        self.path = path
        self.base_path = base_path

    @staticmethod
    def base_fget(attr, instance):
        if isinstance(attr.path, str):
            return find(getattr(instance, attr.base_path), attr.path)
        elif isinstance(attr.path, (list, tuple)):
            return [find(getattr(instance, attr.base_path), k) for k in attr.path]
        else:
            raise TypeError(f"Received unexpected type for path ({type(attr.path)!r}")

    @staticmethod
    def base_fset(attr, instance, value):
        if isinstance(attr.path, str):
            nested_set(getattr(instance, attr.base_path), attr.path, value)
        elif isinstance(attr.path, (list, tuple)):
            for k, v in zip(attr.path, value):
                nested_set(getattr(instance, attr.base_path), k, v)
        else:
            raise TypeError(
                f"Received unexpected type for path ({type(attr.path)!r}, {type(value)!r})"
            )


class Attr(NotRequired, Typed):
    pass


class RequiredAttr(Typed):
    pass


class JSONAttr(JSONLinked, Attr, Validated):
    pass


class RequiredJSONAttr(JSONLinked, RequiredAttr, Validated):
    pass


def is_none(x: Any):
    if isinstance(x, (list, tuple)):
        return all(v is None for v in x)
    else:
        return x is None or x == {}


class SubclassOnlyABC:
    def __new__(cls, *args, **kwargs):
        if cls.__bases__ == (SubclassOnlyABC,):
            raise TypeError(f"Abstract class {cls.__name__} cannot be instantiated")

        return super().__new__(cls)


@dataclass
class ShortReprMixin:
    def __repr__(self):
        clas = self.__class__.__name__
        props = {
            k: getattr(self, k)
            for k, v in self.__class__.__dict__.items()
            if isinstance(v, (Attr, RequiredAttr)) and k not in {"_spec", "_viewspec"}
        }
        settings = [f"{k}={v!r}" for k, v in props.items() if not is_none(v)]
        return "{}({})".format(clas, ", ".join(settings))


def generate_name(length: int = 12) -> str:
    # This implementation roughly based this snippet in core
    # https://github.com/wandb/core/blob/master/lib/js/cg/src/utils/string.ts#L39-L44

    import numpy as np

    rand = np.random.random()
    rand = int(float(str(rand)[2:]))
    rand36 = np.base_repr(rand, 36)
    return rand36.lower()[:length]


def collides(
    p1: "wandb.apis.reports.reports.Panel", p2: "wandb.apis.reports.reports.Panel"
) -> bool:
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


def shift(
    p1: "wandb.apis.reports.reports.Panel", p2: "wandb.apis.reports.reports.Panel"
) -> "Tuple[wandb.apis.reports.reports.Panel, wandb.apis.reports.reports.Panel]":
    l1, l2 = p1.layout, p2.layout

    x = l1["x"] + l1["w"] - l2["x"]
    y = l1["y"] + l1["h"] - l2["y"]

    return x, y


def fix_collisions(
    panels: "List[wandb.apis.reports.reports.Panel]",
) -> "List[wandb.apis.reports.reports.Panel]":
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


def _generate_default_report_spec():
    return {
        "version": 5,
        "panelSettings": {},
        "blocks": [],
        "width": "readable",
        "authors": [],
        "discussionThreads": [],
        "ref": {},
    }


def _generate_default_viewspec():
    return {
        "id": None,
        "name": None,
        "type": "runs",
        "displayName": "Untitled Report",
        "description": "",
        "project": {
            "name": None,
            "entityName": None,
        },
        "spec": _generate_default_report_spec(),
    }


def _generate_default_panel_grid_spec():
    return {
        "type": "panel-grid",
        "children": [{"text": ""}],
        "metadata": {
            "openViz": True,
            "panels": {
                "views": {"0": {"name": "Panels", "defaults": [], "config": []}},
                "tabs": ["0"],
            },
            "panelBankConfig": {
                "state": 0,
                "settings": {
                    "autoOrganizePrefix": 2,
                    "showEmptySections": False,
                    "sortAlphabetically": False,
                },
                "sections": [
                    {
                        "name": "Hidden Panels",
                        "isOpen": False,
                        "panels": [],
                        "type": "flow",
                        "flowConfig": {
                            "snapToColumns": True,
                            "columnsPerPage": 3,
                            "rowsPerPage": 2,
                            "gutterWidth": 16,
                            "boxWidth": 460,
                            "boxHeight": 300,
                        },
                        "sorted": 0,
                        "localPanelSettings": {
                            "xAxis": "_step",
                            "smoothingWeight": 0,
                            "smoothingType": "exponential",
                            "ignoreOutliers": False,
                            "xAxisActive": False,
                            "smoothingActive": False,
                        },
                    }
                ],
            },
            "panelBankSectionConfig": {
                "name": "Report Panels",
                "isOpen": False,
                "panels": [],
                "type": "grid",
                "flowConfig": {
                    "snapToColumns": True,
                    "columnsPerPage": 3,
                    "rowsPerPage": 2,
                    "gutterWidth": 16,
                    "boxWidth": 460,
                    "boxHeight": 300,
                },
                "sorted": 0,
                "localPanelSettings": {
                    "xAxis": "_step",
                    "smoothingWeight": 0,
                    "smoothingType": "exponential",
                    "ignoreOutliers": False,
                    "xAxisActive": False,
                    "smoothingActive": False,
                },
            },
            "customRunColors": {},
            "runSets": [],
            "openRunSet": 0,
            "name": "unused-name",
        },
    }


def _generate_default_runset_spec():
    return {
        "filters": {
            "op": "OR",
            "filters": [{"op": "AND", "filters": []}],
        },
        "runFeed": {
            "version": 2,
            "columnVisible": {"run:name": False},
            "columnPinned": {},
            "columnWidths": {},
            "columnOrder": [],
            "pageSize": 10,
            "onlyShowSelected": False,
        },
        "sort": {
            "keys": [
                {
                    "key": {"section": "run", "name": "createdAt"},
                    "ascending": False,
                }
            ]
        },
        "enabled": True,
        "name": "Run set",
        "search": {"query": ""},
        "project": {"entityName": "megatruong", "name": "report-editing"},
        "grouping": [],
        "selections": {"root": 1, "bounds": [], "tree": []},
        "expandedRowAddresses": [],
    }


def _generate_default_panel_layout():
    return {"x": 0, "y": 0, "w": 8, "h": 6}


def _generate_default_panel_spec():
    return {
        "__id__": generate_name(),
        "viewType": None,
        "config": {},
        # "ref": None,
        "layout": _generate_default_panel_layout(),
    }


defaults_funcs = {
    # "Report": _generate_default_report_spec,
    "Panel": _generate_default_panel_spec,
    "RunSet": _generate_default_runset_spec,
    "PanelGrid": _generate_default_panel_grid_spec,
}


class Base(metaclass=BaseMeta):
    # kinda hacky, but need it to "pre-init" _spec and _viewspec (similar to _attrs today)
    def __new__(cls, *args, **kwargs):
        base_default = cls.__name__
        if base_default not in defaults_funcs:
            base_default = cls.__bases__[0].__name__

        obj = super().__new__(cls)
        f_default = defaults_funcs.get(base_default, lambda: {})
        obj._spec = f_default()
        return obj


class BlockOrPanelBase(Base):
    @classmethod
    def from_json(cls, spec):
        obj = cls()
        obj._spec = spec
        return obj


class RunSetBase(BlockOrPanelBase):
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        obj.query_generator = wandb.apis.public.QueryGenerator()
        obj.pm_query_generator = wandb.apis.public.PythonMongoishQueryGenerator(obj)
        return obj


class ReportBase(metaclass=BaseMeta):
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        obj._viewspec = _generate_default_viewspec()
        obj._orig_viewspec = deepcopy(obj._viewspec)
        return obj

    @classmethod
    def from_viewspec(cls, viewspec):
        # sometimes this doesn't appear in the spec...
        for b in viewspec["spec"]["blocks"]:
            if b["type"] == "panel-grid":
                for rs in b["metadata"]["runSets"]:
                    if "project" not in rs:
                        rs["project"] = {"entityName": "", "name": ""}
        obj = cls(project=viewspec["project"]["name"])
        obj._viewspec = viewspec
        obj._orig_viewspec = deepcopy(viewspec)
        return obj


def tuple_factory(value=None, size=1):
    def _tuple_factory():
        return tuple(value for _ in range(size))

    return _tuple_factory
