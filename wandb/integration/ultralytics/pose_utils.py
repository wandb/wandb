from typing import Optional

import wandb

import numpy as np

from ultralytics.yolo.engine.results import Results
from ultralytics.yolo.utils.plotting import Annotator
from ultralytics.yolo.v8.pose.predict import PosePredictor

from .bbox_utils import get_boxes


def annotate_keypoints(result: Results, visualize_skeleton: bool):
    annotator = Annotator(np.ascontiguousarray(result.orig_img))
    key_points = result.keypoints.data.numpy()
    for idx in range(key_points.shape[0]):
        annotator.kpts(key_points[idx], kpt_line=visualize_skeleton)
    return annotator.im


def plot_pose_predictions(
    result: Results, visualize_skeleton: bool, table: Optional[wandb.Table] = None
):
    result = result.to("cpu")
    boxes, mean_confidence_map = get_boxes(result)
    bbox_image = wandb.Image(result.orig_img[:, :, ::-1], boxes=boxes)
    key_point_image = wandb.Image(annotate_keypoints(result, visualize_skeleton))
    prediction_image = wandb.Image(
        annotate_keypoints(result, visualize_skeleton), boxes=boxes
    )
    table_row = [
        bbox_image,
        key_point_image,
        prediction_image,
        len(boxes["predictions"]["box_data"]),
        mean_confidence_map,
        result.speed,
    ]
    if table is not None:
        table.add_data(*table_row)
        return table
    return table_row
