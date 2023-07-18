import copy
from typing import Dict, Optional, Tuple, Union

import numpy as np
import torch
from ultralytics.yolo.data.augment import LetterBox
from ultralytics.yolo.engine.results import Results
from ultralytics.yolo.utils.ops import scale_image
from ultralytics.yolo.utils.plotting import Annotator, Colors
from ultralytics.yolo.v8.segment import SegmentationPredictor

import wandb

from .bbox_utils import get_ground_truth_bbox_annotations, get_mean_confidence_map


def annotate_mask_results(result: Results):
    colors = Colors()
    annotator = Annotator(result.orig_img)
    predicted_boxes, predicted_masks = result.boxes, result.masks
    img = LetterBox(predicted_masks.shape[1:])(image=annotator.result())
    img_gpu = (
        torch.as_tensor(img, dtype=torch.float16, device=predicted_masks.data.device)
        .permute(2, 0, 1)
        .flip(0)
        .contiguous()
        / 255
    )
    idx = predicted_boxes.cls if predicted_boxes else range(len(predicted_masks))
    annotator.masks(
        predicted_masks.data, colors=[colors(x, True) for x in idx], im_gpu=img_gpu
    )
    return annotator.im


def instance_mask_to_semantic_mask(instance_mask, class_indices):
    height, width, num_instances = instance_mask.shape
    semantic_mask = np.zeros((height, width), dtype=np.uint8)
    for i in range(num_instances):
        instance_map = instance_mask[:, :, i]
        class_index = class_indices[i]
        semantic_mask[instance_map == 1] = class_index
    return semantic_mask


def get_boxes_and_masks(result: Results) -> Tuple[Dict, Dict]:
    boxes = result.boxes.xywh.long().numpy()
    classes = result.boxes.cls.long().numpy() + 1
    confidence = result.boxes.conf.numpy()
    class_id_to_label = {int(k): str(v) for k, v in result.names.items()}
    mean_confidence_map = get_mean_confidence_map(
        classes, confidence, class_id_to_label
    )
    if result.masks is not None:
        scaled_instance_mask = scale_image(
            np.transpose(result.masks.data.numpy(), (1, 2, 0)),
            result.orig_img[:, :, ::-1].shape,
        )
        scaled_semantic_mask = instance_mask_to_semantic_mask(
            scaled_instance_mask, classes.tolist()
        )
        class_id_to_label_segmentation = {
            int(k) + 1: str(v) for k, v in copy.deepcopy(class_id_to_label).items()
        }
        class_id_to_label_segmentation.update({0: "background"})
        masks = {
            "predictions": {
                "mask_data": scaled_semantic_mask,
                "class_labels": class_id_to_label_segmentation,
            }
        }
    else:
        masks = None
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
    result: Results, table: Optional[wandb.Table] = None
) -> Union[wandb.Table, Tuple[wandb.Image, Dict, Dict]]:
    result = result.to("cpu")
    boxes, masks, mean_confidence_map = get_boxes_and_masks(result)
    image = wandb.Image(result.orig_img[:, :, ::-1], boxes=boxes, masks=masks)
    if table is not None:
        table.add_data(
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
            ) = plot_mask_predictions(prediction_result)
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
                table.add_data(*table_rows)
                data_idx += 1
            except TypeError:
                pass
        if batch_idx + 1 == max_validation_batches:
            break
    return table
