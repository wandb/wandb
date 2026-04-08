from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class Attrs:
    def __init__(self, attrs: Mapping[str, Any]):
        self._attrs = dict(attrs)

    def snake_to_camel(self, string):
        camel = "".join([i.title() for i in string.split("_")])
        return camel[0].lower() + camel[1:]

    def __getattr__(self, name):
        key = self.snake_to_camel(name)
        if key == "user":
            raise AttributeError
        if key in self._attrs:
            return self._attrs[key]
        elif name in self._attrs:
            return self._attrs[name]
        else:
            raise AttributeError(f"{repr(self)!r} object has no attribute {name!r}")
