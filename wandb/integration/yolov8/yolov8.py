from typing import Union

import wandb

from ultralytics.yolo.v8.detect.val import DetectionValidator
from ultralytics.yolo.v8.detect.predict import DetectionPredictor

from .bbox_utils import plot_validation_results, plot_predictions


def plot_bboxes(trainer: Union[DetectionValidator, DetectionPredictor]):
    if isinstance(trainer, DetectionValidator):
        validator = trainer
        dataloader = validator.dataloader
        class_label_map = validator.names
        plot_validation_results(dataloader, class_label_map)

    elif isinstance(trainer, DetectionPredictor):
        predictor = trainer
        results = predictor.results
        table = wandb.Table(columns=["Image", "Num-Objects", "Mean-Confidence"])
        for idx, result in enumerate(results):
            table = plot_predictions(result, table)
        wandb.log({"Object-Detection-Table": table})
