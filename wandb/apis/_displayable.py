from __future__ import annotations

from abc import ABC, abstractmethod

import wandb
from wandb._strutils import nameof
from wandb.sdk.lib.ipython import in_jupyter


class DisplayableMixin(ABC):
    """A mixin class for objects that can be displayed as HTML in jupyter environments.

    <!-- lazydoc-ignore-class: internal -->
    """

    @abstractmethod
    def to_html(self, height: int = 420, hidden: bool = False) -> str:
        raise NotImplementedError

    def display(self, height: int = 420, hidden: bool = False) -> bool:
        """Display this object in jupyter."""
        if ((run := wandb.run) and run._settings.silent) or not in_jupyter():
            return False

        try:
            from IPython.display import display_html
        except ImportError:
            msg = f"{nameof(self.display)}() only works in jupyter environments"
            wandb.termwarn(msg)
            return False

        display_html(self.to_html(height=height, hidden=hidden))
        return True

    def _repr_html_(self) -> str:
        return self.to_html()
