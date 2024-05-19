"""This is a rewrite of the expression system currently used in Reports.

In a future version, Reports will migrate to this expression syntax.
"""

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Union

from wandb.apis.reports.v2.internal import SortKey, SortKeyKey

from ..reports.v2.internal import Filters, Key

Expression = Dict[str, Any]


class InvertableDict(MutableMapping):
    def __init__(self, *args, **kwargs):
        self._forward = dict(*args, **kwargs)
        self._backward = {}
        for key, value in self._forward.items():
            if value in self._backward:
                raise ValueError(f"Duplicate value found: {value}")
            self._backward[value] = key

    def __getitem__(self, key):
        return self._forward[key]

    def __setitem__(self, key, value):
        if key in self._forward:
            del self._backward[self._forward[key]]
        if value in self._backward:
            raise ValueError(f"Duplicate value found: {value}")
        self._forward[key] = value
        self._backward[value] = key

    def __delitem__(self, key):
        value = self._forward.pop(key)
        del self._backward[value]

    def __iter__(self):
        return iter(self._forward)

    def __len__(self):
        return len(self._forward)

    def __repr__(self):
        return repr(self._forward)

    def __contains__(self, key):
        return key in self._forward

    @property
    def inv(self):
        return self._backward


FE_BE_NAME_MAP = InvertableDict(
    {
        "ID": "name",
        "Name": "displayName",
        "Tags": "tags",
        "State": "state",
        "CreatedTimestamp": "createdAt",
        "Runtime": "duration",
        "User": "username",
        "Sweep": "sweep",
        "Group": "group",
        "JobType": "jobType",
        "Hostname": "host",
        "UsingArtifact": "inputArtifacts",
        "OutputtingArtifact": "outputArtifacts",
        "Step": "_step",
        "RelativeTime(Wall)": "_absolute_runtime",
        "RelativeTime(Process)": "_runtime",
        "WallTime": "_timestamp",
    }
)


# Mapping custom operators to Python operators
OPERATOR_MAP = InvertableDict(
    {
        "AND": "and",
        "OR": "or",
        "=": "==",
        "!=": "!=",
        "<": "<",
        "<=": "<=",
        ">": ">",
        ">=": ">=",
        "IN": "in",
        "NIN": "not in",
    }
)

SECTION_MAP = InvertableDict(
    {
        "Metric": "run",
        "Summary": "summary",
        "Config": "config",
        "Tags": "tags",
        "KeysInfo": "keys_info",
    }
)


@dataclass(eq=False, frozen=True)
class BaseMetric:
    name: str
    section: ClassVar[str]  # declared in subclasses

    def __eq__(self, other: Any) -> "FilterExpr":
        return FilterExpr.create("=", self, other)

    def __ne__(self, other: Any) -> "FilterExpr":
        return FilterExpr.create("!=", self, other)

    def __lt__(self, other: Any) -> "FilterExpr":
        return FilterExpr.create("<", self, other)

    def __le__(self, other: Any) -> "FilterExpr":
        return FilterExpr.create("<=", self, other)

    def __gt__(self, other: Any) -> "FilterExpr":
        return FilterExpr.create(">", self, other)

    def __ge__(self, other: Any) -> "FilterExpr":
        return FilterExpr.create(">=", self, other)

    def isin(self, other: List[Any]) -> "FilterExpr":
        return FilterExpr.create("IN", self, other)

    def notin(self, other: List[Any]) -> "FilterExpr":
        return FilterExpr.create("NIN", self, other)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('{self.name}')"

    def to_key(self) -> Key:
        name = FE_BE_NAME_MAP.get(self.name, self.name)
        return Key(section=self.section, name=name)

    @classmethod
    def from_key(cls, key: Key) -> "BaseMetric":
        section = key.section
        name = FE_BE_NAME_MAP.inv.get(key.name, key.name)
        metric_cls = SECTION_CLASS_MAP.get(section, BaseMetric)
        return metric_cls(name)


@dataclass(eq=False, frozen=True)
class Metric(BaseMetric):
    """Typically metrics that you log with `wandb.log`.

    These also include any metrics that are logged automatically as part of the run, like `Created Timestamp`
    """

    section: ClassVar[str] = SECTION_MAP["Metric"]


@dataclass(eq=False, frozen=True)
class Summary(BaseMetric):
    """Typically the last value for metrics that you log with `wandb.log`."""

    section: ClassVar[str] = SECTION_MAP["Summary"]


@dataclass(eq=False, frozen=True)
class Config(BaseMetric):
    """Typically the values you log when setting `wandb.config`."""

    section: ClassVar[str] = SECTION_MAP["Config"]


@dataclass(eq=False, frozen=True)
class Tags(BaseMetric):
    """The values when setting `wandb.run.tags`."""

    section: ClassVar[str] = SECTION_MAP["Tags"]


@dataclass(eq=False, frozen=True)
class KeysInfo(BaseMetric):
    """You probably don't need this.

    This is a special section that contains information about the keys in the other sections.
    """

    section: ClassVar[str] = SECTION_MAP["KeysInfo"]


SECTION_CLASS_MAP = InvertableDict(
    {
        "run": Metric,
        "summary": Summary,
        "config": Config,
        "tags": Tags,
        "keys_info": KeysInfo,
    }
)


@dataclass(frozen=True)
class Ordering:
    item: BaseMetric
    ascending: bool = True

    def to_key(self) -> SortKey:
        k = self.item.to_key()
        skk = SortKeyKey(section=k.section, name=k.name)
        return SortKey(key=skk, ascending=self.ascending)

    @classmethod
    def from_key(cls, key: SortKey) -> "Ordering":
        item = BaseMetric.from_key(key.key)
        return cls(item, key.ascending)


@dataclass
class FilterExpr:
    """A converted expression to be used in W&B Filters.

    Don't instantiate this class directly.  Instead, use one of the base metrics above
    (e.g. Metric, Summary, Config, etc) and use the comparison operators to create a FilterExpr

    For example:
      - Metric("loss") < 0.5; or
      - Config("model").isin(["resnet", "densenet"])
    """

    op: str
    key: BaseMetric
    value: Any

    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            """Don't instantiate this class directly.  Instead, write an expression using the base metrics, e.g. Metric("loss") < 0.5"""
        )

    @classmethod
    def create(cls, op: str, key: BaseMetric, value: Any):
        key_cls = key.__class__
        mapped_name = FE_BE_NAME_MAP.inv.get(key.name, key.name)
        new_key = key_cls(mapped_name)

        instance = cls.__new__(cls)
        instance.op = op
        instance.key = new_key
        instance.value = value
        return instance

    def __repr__(self) -> str:
        return f"({self.key} {OPERATOR_MAP[self.op]} {repr(self.value)})"

    def to_model(self) -> Filters:
        section = self.key.section
        name = self.key.name

        return Filters(
            op=self.op,
            key=Key(section=section, name=FE_BE_NAME_MAP.get(name, name)),
            value=self.value,
            disabled=False,
        )


def expression_tree_to_filters(expr: Filters) -> List[FilterExpr]:
    def parse_filter(filter: Filters) -> FilterExpr:
        key = filter.key
        if key is None:
            return None
        metric_cls = SECTION_CLASS_MAP.get(key.section, BaseMetric)
        metric = metric_cls(key.name)
        return FilterExpr.create(filter.op, metric, filter.value)

    def parse_expression(expr: Filters) -> List[FilterExpr]:
        if expr.filters:
            filters = []
            for f in expr.filters:
                filters.extend(parse_expression(f))
            return filters
        else:
            return [parse_filter(expr)]

    return parse_expression(expr)


def filters_to_expression_tree(filters: List[FilterExpr]) -> Filters:
    def parse_key(metric: BaseMetric) -> Key:
        section = metric.section
        return Key(section=section, name=metric.name)

    def parse_filter(filter: FilterExpr) -> Filters:
        key = parse_key(filter.key)
        return Filters(op=filter.op, key=key, value=filter.value, disabled=False)

    return Filters(op="AND", filters=[parse_filter(f) for f in filters])


def grouping_backend_to_frontend(grouping: str) -> str:
    return FE_BE_NAME_MAP.get(grouping, grouping)


MetricType = Union[Metric, Summary, Config, Tags, KeysInfo]
