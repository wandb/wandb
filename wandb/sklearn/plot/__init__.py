"""Create and logs charts introspecting models built with scikit-learn to W&B."""

from .classifier import calibration_curve as plot_calibration_curve
from .classifier import class_proportions as plot_class_proportions
from .classifier import classifier as plot_classifier
from .classifier import confusion_matrix as plot_confusion_matrix
from .classifier import feature_importances as plot_feature_importances
from .classifier import precision_recall as plot_precision_recall
from .classifier import roc as plot_roc
from .clusterer import clusterer as plot_clusterer
from .clusterer import elbow_curve as plot_elbow_curve
from .clusterer import silhouette as plot_silhouette
from .regressor import outlier_candidates as plot_outlier_candidates
from .regressor import regressor as plot_regressor
from .regressor import residuals as plot_residuals
from .shared import learning_curve as plot_learning_curve
from .shared import summary_metrics as plot_summary_metrics

__all__ = [
    "plot_classifier",
    "plot_clusterer",
    "plot_regressor",
    "plot_summary_metrics",
    "plot_learning_curve",
    "plot_feature_importances",
    "plot_class_proportions",
    "plot_calibration_curve",
    "plot_roc",
    "plot_precision_recall",
    "plot_confusion_matrix",
    "plot_elbow_curve",
    "plot_silhouette",
    "plot_residuals",
    "plot_outlier_candidates",
]
