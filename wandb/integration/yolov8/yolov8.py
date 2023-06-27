from typing import Union

import wandb

from ultralytics.yolo.v8.detect.train import DetectionTrainer
from ultralytics.yolo.v8.detect.val import DetectionValidator
from ultralytics.yolo.v8.detect.predict import DetectionPredictor

from .bbox_utils import plot_ground_truth, plot_predictions


def plot_bboxes(trainer: Union[DetectionTrainer, DetectionPredictor]):
    if isinstance(trainer, DetectionTrainer):
        dataloader = trainer.validator.dataloader
        class_label_map = trainer.validator.names
        plot_ground_truth(dataloader, class_label_map)

    elif isinstance(trainer, DetectionPredictor):
        predictor = trainer
        results = predictor.results
        table = wandb.Table(columns=["Image", "Num-Objects", "Mean-Confidence"])
        for idx, result in enumerate(results):
            table = plot_predictions(result, table)
        wandb.log({"Object-Detection-Table": table})
