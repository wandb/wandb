import logging
import sys
import warnings
from typing import Optional

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

import wandb

PythonType = Literal["python", "ipython", "jupyter"]

logger = logging.getLogger(__name__)


TABLE_STYLES = """<style>
    table.wandb td:nth-child(1) { padding: 0 10px; text-align: left ; width: auto;} td:nth-child(2) {text-align: left ; width: 100%}
    .wandb-row { display: flex; flex-direction: row; flex-wrap: wrap; justify-content: flex-start; width: 100% }
    .wandb-col { display: flex; flex-direction: column; flex-basis: 100%; flex: 1; padding: 10px; }
    </style>
"""


def toggle_button(what="run"):
    return f"<button onClick=\"this.nextSibling.style.display='block';this.style.display='none';\">Display W&B {what}</button>"


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
    return _get_python_type() == "jupyter"


def in_notebook() -> bool:
    return _get_python_type() != "python"


def display_html(html: str):  # type: ignore
    """Display HTML in notebooks, is a noop outside a jupyter context."""
    if wandb.run and wandb.run._settings.silent:
        return
    try:
        from IPython.core.display import HTML, display  # type: ignore
    except ImportError:
        wandb.termwarn("Unable to render HTML, can't import display from ipython.core")
        return False
    return display(HTML(html))


def display_widget(widget):
    """Display ipywidgets in notebooks, is a noop outside of a jupyter context."""
    if wandb.run and wandb.run._settings.silent:
        return
    try:
        from IPython.core.display import display
    except ImportError:
        wandb.termwarn(
            "Unable to render Widget, can't import display from ipython.core"
        )
        return False
    return display(widget)


class ProgressWidget:
    """A simple wrapper to render a nice progress bar with a label."""

    def __init__(self, widgets, min, max):
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
                display_widget(self._widget)
        except Exception as e:
            self._disabled = True
            logger.exception(e)
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
