from typing import Any, Optional

import numpy as np
from PIL import Image
from ultralytics.engine.results import Results
from ultralytics.models.yolo.pose import PosePredictor
from ultralytics.utils.plotting import Annotator

import wandb

from .bbox_utils import get_boxes, get_ground_truth_bbox_annotations


def annotate_keypoint_results(result: Results, visualize_skeleton: bool):
    annotator = Annotator(np.ascontiguousarray(result.orig_img[:, :, ::-1]))
    key_points = result.keypoints.data.numpy()
    for idx in range(key_points.shape[0]):
        annotator.kpts(key_points[idx], kpt_line=visualize_skeleton)
    return annotator.im


def annotate_keypoint_batch(image_path: str, keypoints: Any, visualize_skeleton: bool):
    original_image = None
    with Image.open(image_path) as original_image:
        original_image = np.ascontiguousarray(original_image)
        annotator = Annotator(original_image)
        annotator.kpts(keypoints.numpy(), kpt_line=visualize_skeleton)
        return annotator.im


def plot_pose_predictions(
    result: Results,
    model_name: str,
    visualize_skeleton: bool,
    table: Optional[wandb.Table] = None,
):
    result = result.to("cpu")
    boxes, mean_confidence_map = get_boxes(result)
    prediction_image = wandb.Image(
        annotate_keypoint_results(result, visualize_skeleton), boxes=boxes
    )
    table_row = [
        model_name,
        prediction_image,
        len(boxes["predictions"]["box_data"]),
        mean_confidence_map,
        result.speed,
    ]
    if table is not None:
        table.add_data(*table_row)
        return table
    return table_row


def plot_pose_validation_results(
    dataloader,
    class_label_map,
    model_name: str,
    predictor: PosePredictor,
    visualize_skeleton: bool,
    table: wandb.Table,
    max_validation_batches: int,
    epoch: Optional[int] = None,
) -> wandb.Table:
    data_idx = 0
    for batch_idx, batch in enumerate(dataloader):
        for img_idx, image_path in enumerate(batch["im_file"]):
            prediction_result = predictor(image_path)[0].to("cpu")
            table_row = plot_pose_predictions(
                prediction_result, model_name, visualize_skeleton
            )
            ground_truth_image = wandb.Image(
                annotate_keypoint_batch(
                    image_path, batch["keypoints"][img_idx], visualize_skeleton
                ),
                boxes={
                    "ground-truth": {
                        "box_data": get_ground_truth_bbox_annotations(
                            img_idx, image_path, batch, class_label_map
                        ),
                        "class_labels": class_label_map,
                    },
                },
            )
            table_row = [data_idx, batch_idx, ground_truth_image] + table_row[1:]
            table_row = [epoch] + table_row if epoch is not None else table_row
            table_row = [model_name] + table_row
            table.add_data(*table_row)
            data_idx += 1
        if batch_idx + 1 == max_validation_batches:
            break
    return table
