"""Chart Visualization Utilities

This module offers a collection of predefined chart types, along with functionality
for creating custom charts, enabling flexible visualization of your data beyond the
built-in options.
"""

__all__ = [
    "line",
    "histogram",
    "scatter",
    "bar",
    "roc_curve",
    "pr_curve",
    "confusion_matrix",
    "line_series",
]

from wandb.plot.bar import bar
from wandb.plot.confusion_matrix import confusion_matrix
from wandb.plot.custom_chart import CustomChart, plot_table
from wandb.plot.histogram import histogram
from wandb.plot.line import line
from wandb.plot.line_series import line_series
from wandb.plot.pr_curve import pr_curve
from wandb.plot.roc_curve import roc_curve
from wandb.plot.scatter import scatter
from wandb.plot.viz import Visualize, visualize
