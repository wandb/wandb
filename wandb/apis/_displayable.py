from __future__ import annotations

from abc import ABC, abstractmethod

import wandb
from wandb._strutils import nameof
from wandb.sdk.lib import ipython


class DisplayableMixin(ABC):
    """A mixin class for objects that can be displayed as HTML in jupyter environments.

    <!-- lazydoc-ignore-class: internal -->
    """

    @abstractmethod
    def to_html(self, height: int = 420, hidden: bool = False) -> str:
        raise NotImplementedError

    def display(self, height: int = 420, hidden: bool = False) -> bool:
        """Display this object in jupyter."""
        if (wandb.run and wandb.run._settings.silent) or not ipython.in_jupyter():
            return False

        try:
            from IPython import display
        except ImportError:
            wandb.termwarn(
                f"{nameof(self.display)}() only works in jupyter environments"
            )
            return False
        else:
            html = self.to_html(height, hidden)
            display.display(display.HTML(html))
            return True

    def _repr_html_(self) -> str:
        return self.to_html()
