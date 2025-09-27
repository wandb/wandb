from __future__ import annotations

from typing import Any, MutableMapping

import wandb

from ..sdk.lib import ipython


class Attrs:
    def __init__(self, attrs: MutableMapping[str, Any]):
        self._attrs = attrs

    def snake_to_camel(self, string):
        camel = "".join([i.title() for i in string.split("_")])
        return camel[0].lower() + camel[1:]

    def display(self, height=420, hidden=False) -> bool:
        """Display this object in jupyter."""
        if wandb.run and wandb.run._settings.silent:
            return False

        if not ipython.in_jupyter():
            return False

        html = self.to_html(height, hidden)
        if html is None:
            wandb.termwarn("This object does not support `.display()`")
            return False

        try:
            from IPython import display
        except ImportError:
            wandb.termwarn(".display() only works in jupyter environments")
            return False

        display.display(display.HTML(html))
        return True

    def to_html(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        key = self.snake_to_camel(name)
        if key == "user":
            raise AttributeError
        if key in self._attrs.keys():
            return self._attrs[key]
        elif name in self._attrs.keys():
            return self._attrs[name]
        else:
            raise AttributeError(f"{repr(self)!r} object has no attribute {name!r}")
