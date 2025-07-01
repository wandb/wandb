import logging
import sys
import warnings
from typing import Literal, Optional

import wandb

PythonType = Literal["python", "ipython", "jupyter"]

logger = logging.getLogger(__name__)


def toggle_button(what="run"):
    """Returns the HTML for a button used to reveal the element following it.

    The element immediately after the button must have `display: none`.
    """
    return (
        "<button onClick=\"this.nextSibling.style.display='block';this.style.display='none';\">"
        f"Display W&B {what}"
        "</button>"
    )


def _get_python_type() -> PythonType:
    if "IPython" not in sys.modules:
        return "python"

    try:
        from IPython import get_ipython  # type: ignore

        # Calling get_ipython can cause an ImportError
        if get_ipython() is None:
            return "python"
    except ImportError:
        return "python"

    # jupyter-based environments (e.g. jupyter itself, colab, kaggle, etc) have a connection file
    ip_kernel_app_connection_file = (
        (get_ipython().config.get("IPKernelApp", {}) or {})
        .get("connection_file", "")
        .lower()
    ) or (
        (get_ipython().config.get("ColabKernelApp", {}) or {})
        .get("connection_file", "")
        .lower()
    )

    if (
        ("terminal" in get_ipython().__module__)
        or ("jupyter" not in ip_kernel_app_connection_file)
        or ("spyder" in sys.modules)
    ):
        return "ipython"
    else:
        return "jupyter"


def in_jupyter() -> bool:
    """Returns True if we're in a Jupyter notebook."""
    return _get_python_type() == "jupyter"


def in_ipython() -> bool:
    """Returns True if we're running in IPython in the terminal."""
    return _get_python_type() == "ipython"


def in_notebook() -> bool:
    """Returns True if we're running in Jupyter or IPython."""
    return _get_python_type() != "python"


class ProgressWidget:
    """A simple wrapper to render a nice progress bar with a label."""

    def __init__(self, widgets, min, max):
        from IPython import display

        self._ipython_display = display

        self.widgets = widgets
        self._progress = widgets.FloatProgress(min=min, max=max)
        self._label = widgets.Label()
        self._widget = self.widgets.VBox([self._label, self._progress])
        self._displayed = False
        self._disabled = False

    def update(self, value: float, label: str) -> None:
        if self._disabled:
            return
        try:
            self._progress.value = value
            self._label.value = label
            if not self._displayed:
                self._displayed = True
                self._ipython_display.display(self._widget)
        except Exception:
            logger.exception("Error in ProgressWidget.update()")
            self._disabled = True
            wandb.termwarn(
                "Unable to render progress bar, see the user log for details"
            )

    def close(self) -> None:
        if self._disabled or not self._displayed:
            return
        self._widget.close()


def jupyter_progress_bar(min: float = 0, max: float = 1.0) -> Optional[ProgressWidget]:
    """Return an ipywidget progress bar or None if we can't import it."""
    widgets = wandb.util.get_module("ipywidgets")
    try:
        if widgets is None:
            # TODO: this currently works in iPython but it's deprecated since 4.0
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from IPython.html import widgets  # type: ignore

        assert hasattr(widgets, "VBox")
        assert hasattr(widgets, "Label")
        assert hasattr(widgets, "FloatProgress")
        return ProgressWidget(widgets, min=min, max=max)
    except (ImportError, AssertionError):
        return None
