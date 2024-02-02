from typing import Optional

from ...public import PanelMetricsHelper, Run
from .runset import Runset
from .util import Attr, Base, Panel, nested_get, nested_set


class LineKey:
    def __init__(self, key: str) -> None:
        self.key = key

    def __hash__(self) -> int:
        return hash(self.key)

    def __repr__(self) -> str:
        return f"LineKey(key={self.key!r})"

    @classmethod
    def from_run(cls, run: "Run", metric: str) -> "LineKey":
        key = f"{run.id}:{metric}"
        return cls(key)

    @classmethod
    def from_panel_agg(cls, runset: "Runset", panel: "Panel", metric: str) -> "LineKey":
        key = f"{runset.id}-config:group:{panel.groupby}:null:{metric}"
        return cls(key)

    @classmethod
    def from_runset_agg(cls, runset: "Runset", metric: str) -> "LineKey":
        groupby = runset.groupby
        if runset.groupby is None:
            groupby = "null"

        key = f"{runset.id}-run:group:{groupby}:{metric}"
        return cls(key)


class PCColumn(Base):
    metric: str = Attr(json_path="spec.accessor")
    name: Optional[str] = Attr(json_path="spec.displayName")
    ascending: Optional[bool] = Attr(json_path="spec.inverted")
    log_scale: Optional[bool] = Attr(json_path="spec.log")

    def __init__(
        self, metric, name=None, ascending=None, log_scale=None, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.panel_metrics_helper = PanelMetricsHelper()
        self.metric = metric
        self.name = name
        self.ascending = ascending
        self.log_scale = log_scale

    @classmethod
    def from_json(cls, spec):
        obj = cls(metric=spec["accessor"])
        obj._spec = spec
        return obj

    @metric.getter
    def metric(self):
        json_path = self._get_path("metric")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.special_back_to_front(value)

    @metric.setter
    def metric(self, value):
        json_path = self._get_path("metric")
        value = self.panel_metrics_helper.special_front_to_back(value)
        nested_set(self, json_path, value)
