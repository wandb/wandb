from typing import Dict, Optional, Tuple

import numpy as np
from ultralytics.engine.results import Results
from ultralytics.models.yolo.segment import SegmentationPredictor
from ultralytics.utils.ops import scale_image

import wandb

from .bbox_utils import get_ground_truth_bbox_annotations, get_mean_confidence_map


def instance_mask_to_semantic_mask(instance_mask, class_indices):
    height, width, num_instances = instance_mask.shape
    semantic_mask = np.zeros((height, width), dtype=np.uint8)
    for i in range(num_instances):
        instance_map = instance_mask[:, :, i]
        class_index = class_indices[i]
        semantic_mask[instance_map == 1] = class_index
    return semantic_mask


def get_boxes_and_masks(result: Results) -> Tuple[Dict, Dict, Dict]:
    boxes = result.boxes.xywh.long().numpy()
    classes = result.boxes.cls.long().numpy()
    confidence = result.boxes.conf.numpy()
    class_id_to_label = {int(k): str(v) for k, v in result.names.items()}
    class_id_to_label.update({len(result.names.items()): "background"})
    mean_confidence_map = get_mean_confidence_map(
        classes, confidence, class_id_to_label
    )
    masks = None
    if result.masks is not None:
        scaled_instance_mask = scale_image(
            np.transpose(result.masks.data.numpy(), (1, 2, 0)),
            result.orig_img[:, :, ::-1].shape,
        )
        scaled_semantic_mask = instance_mask_to_semantic_mask(
            scaled_instance_mask, classes.tolist()
        )
        scaled_semantic_mask[scaled_semantic_mask == 0] = len(result.names.items())
        masks = {
            "predictions": {
                "mask_data": scaled_semantic_mask,
                "class_labels": class_id_to_label,
            }
        }
    box_data, total_confidence = [], 0.0
    for idx in range(len(boxes)):
        box_data.append(
            {
                "position": {
                    "middle": [int(boxes[idx][0]), int(boxes[idx][1])],
                    "width": int(boxes[idx][2]),
                    "height": int(boxes[idx][3]),
                },
                "domain": "pixel",
                "class_id": int(classes[idx]),
                "box_caption": class_id_to_label[int(classes[idx])],
                "scores": {"confidence": float(confidence[idx])},
            }
        )
        total_confidence += float(confidence[idx])

    boxes = {
        "predictions": {
            "box_data": box_data,
            "class_labels": class_id_to_label,
        },
    }
    return boxes, masks, mean_confidence_map


def plot_mask_predictions(
    result: Results, model_name: str, table: Optional[wandb.Table] = None
) -> Tuple[wandb.Image, Dict, Dict, Dict]:
    result = result.to("cpu")
    boxes, masks, mean_confidence_map = get_boxes_and_masks(result)
    image = wandb.Image(result.orig_img[:, :, ::-1], boxes=boxes, masks=masks)
    if table is not None:
        table.add_data(
            model_name,
            image,
            len(boxes["predictions"]["box_data"]),
            mean_confidence_map,
            result.speed,
        )
        return table
    return image, masks, boxes["predictions"], mean_confidence_map


def plot_mask_validation_results(
    dataloader,
    class_label_map,
    model_name: str,
    predictor: SegmentationPredictor,
    table: wandb.Table,
    max_validation_batches: int,
    epoch: Optional[int] = None,
):
    data_idx = 0
    for batch_idx, batch in enumerate(dataloader):
        for img_idx, image_path in enumerate(batch["im_file"]):
            prediction_result = predictor(image_path)[0]
            (
                _,
                prediction_mask_data,
                prediction_box_data,
                mean_confidence_map,
            ) = plot_mask_predictions(prediction_result, model_name)
            try:
                ground_truth_data = get_ground_truth_bbox_annotations(
                    img_idx, image_path, batch, class_label_map
                )
                wandb_image = wandb.Image(
                    image_path,
                    boxes={
                        "ground-truth": {
                            "box_data": ground_truth_data,
                            "class_labels": class_label_map,
                        },
                        "predictions": prediction_box_data,
                    },
                    masks=prediction_mask_data,
                )
                table_rows = [
                    data_idx,
                    batch_idx,
                    wandb_image,
                    mean_confidence_map,
                    prediction_result.speed,
                ]
                table_rows = [epoch] + table_rows if epoch is not None else table_rows
                table_rows = [model_name] + table_rows
                table.add_data(*table_rows)
                data_idx += 1
            except TypeError:
                pass
        if batch_idx + 1 == max_validation_batches:
            break
    return table
