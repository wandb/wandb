#
import logging
import sys

import wandb

logger = logging.getLogger(__name__)


STYLED_TABLE_HTML = """<style>
    table.wandb td:nth-child(1) { padding: 0 10px; text-align: right }
    </style><table class="wandb">
"""


def _get_python_type():
    try:
        from IPython import get_ipython  # type: ignore
    except ImportError:
        return "python"
    if get_ipython() is None:
        return "python"
    elif "terminal" in get_ipython().__module__ or "spyder" in sys.modules:
        return "ipython"
    else:
        return "jupyter"


def display_html(html):
    """Displays HTML in notebooks, is a noop outside of a jupyter context"""
    if wandb.run and wandb.run._settings._silent:
        return
    try:
        from IPython.core.display import display, HTML  # type: ignore
    except ImportError:
        wandb.termwarn("Unable to render HTML, can't import display from ipython.core")
        return False
    return display(HTML(html))


def display_widget(widget):
    """Displays ipywidgets in notebooks, is a noop outside of a jupyter context"""
    if wandb.run and wandb.run._settings._silent:
        return
    try:
        from IPython.core.display import display
    except ImportError:
        wandb.termwarn(
            "Unable to render Widget, can't import display from ipython.core"
        )
        return False
    return display(widget)


class ProgressWidget(object):
    """A simple wrapper to render a nice progress bar with a label"""

    def __init__(self, widgets, min, max):
        self.widgets = widgets
        self._progress = widgets.FloatProgress(min=min, max=max)
        self._label = widgets.Label()
        self._widget = self.widgets.VBox([self._label, self._progress])
        self._displayed = False
        self._disabled = False

    def update(self, value, label):
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

    def close(self):
        if self._disabled or not self._displayed:
            return
        self._widget.close()


def jupyter_progress_bar(min=0, max=1.0):
    """Returns an ipywidget progress bar or None if we can't import it"""
    widgets = wandb.util.get_module("ipywidgets")
    try:
        if widgets is None:
            # TODO: this currently works in iPython but it's deprecated since 4.0
            from IPython.html import widgets  # type: ignore

        assert hasattr(widgets, "VBox")
        assert hasattr(widgets, "Label")
        assert hasattr(widgets, "FloatProgress")
        return ProgressWidget(widgets, min=min, max=max)
    except (ImportError, AssertionError):
        return None
