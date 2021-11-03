"""Creates and logs charts introspecting models built with scikit-learn to W&B."""
from .shared import (
    summary_metrics as plot_summary_metrics,
    learning_curve as plot_learning_curve,
)

from .classifier import (
    classifier as plot_classifier,
    feature_importances as plot_feature_importances,
    class_proportions as plot_class_proportions,
    calibration_curve as plot_calibration_curve,
    roc as plot_roc,
    precision_recall as plot_precision_recall,
    confusion_matrix as plot_confusion_matrix,
    decision_boundaries as plot_decision_boundaries,
)

from .clusterer import (
    clusterer as plot_clusterer,
    elbow_curve as plot_elbow_curve,
    silhouette as plot_silhouette,
)

from .regressor import (
    regressor as plot_regressor,
    residuals as plot_residuals,
    outlier_candidates as plot_outlier_candidates,
)


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
    "plot_decision_boundaries",
    "plot_elbow_curve",
    "plot_silhouette",
    "plot_residuals",
    "plot_outlier_candidates",
]
