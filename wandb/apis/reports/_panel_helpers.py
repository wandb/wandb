__all__ = ["LineKey", "RGBA"]

from dataclasses import dataclass
import re

from wandb.apis.reports.util import Attr
from wandb.apis.reports.validators import between


@dataclass
class LineKey:
    def __init__(self, key):
        self.key = key

    def __hash__(self):
        return hash(self.key)

    def __repr__(self):
        return f'LineKey(key="{self.key}")'

    @classmethod
    def from_run(cls, run, metric):
        key = f"{run.id}:{metric}"
        return cls(key)

    @classmethod
    def from_panel_agg(cls, runset, panel, metric):
        key = f"{runset.id}-config:group:{panel.groupby}:null:{metric}"
        return cls(key)

    @classmethod
    def from_runset_agg(cls, runset, metric):
        groupby = runset.groupby
        if runset.groupby is None:
            groupby = "null"

        key = f"{runset.id}-run:group:{groupby}:{metric}"
        return cls(key)


@dataclass
class RGBA:
    r: int = Attr(int, validators=[between(0, 255)])
    g: int = Attr(int, validators=[between(0, 255)])
    b: int = Attr(int, validators=[between(0, 255)])
    a: float = Attr((int, float), validators=[between(0, 1)])

    @classmethod
    def from_json(cls, d):
        color = d.get("transparentColor").replace(" ", "")
        r, g, b, a = re.split(r"\(|\)|,", color)[1:-1]
        r, g, b, a = int(r), int(g), int(b), float(a)
        return cls(r, g, b, a)

    @property
    def spec(self):
        return {
            "color": f"rgb({self.r}, {self.g}, {self.b})",
            "transparentColor": f"rgba({self.r}, {self.g}, {self.b}, {self.a})",
        }
