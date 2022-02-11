"""Create informative charts for scikit-learn models and log them to W&B."""
from .plot import plot_classifier, plot_clusterer, plot_regressor
from .plot import (
    plot_summary_metrics,
    plot_learning_curve,
    plot_roc,
    plot_confusion_matrix,
    plot_precision_recall,
    plot_feature_importances,
    plot_elbow_curve,
    plot_silhouette,
    plot_class_proportions,
    plot_calibration_curve,
    plot_outlier_candidates,
    plot_residuals,
    plot_decision_boundaries,
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
