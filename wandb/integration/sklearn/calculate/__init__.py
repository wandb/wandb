"""Calculates and formats metrics and charts for introspecting sklearn models.

The functions in these modules are designed to be called by functions from the
plot submodule that have been exported into the namespace of the wandb.sklearn
submodule, rather than being called directly.
"""

from .calibration_curves import calibration_curves
from .class_proportions import class_proportions
from .confusion_matrix import confusion_matrix
from .decision_boundaries import decision_boundaries
from .elbow_curve import elbow_curve
from .feature_importances import feature_importances
from .learning_curve import learning_curve
from .outlier_candidates import outlier_candidates
from .residuals import residuals
from .silhouette import silhouette
from .summary_metrics import summary_metrics

__all__ = [
    "calibration_curves",
    "class_proportions",
    "confusion_matrix",
    "decision_boundaries",
    "elbow_curve",
    "feature_importances",
    "learning_curve",
    "outlier_candidates",
    "residuals",
    "silhouette",
    "summary_metrics",
]
