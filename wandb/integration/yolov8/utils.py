"""
Utilities for parsing and plotting Yolo results using wandb.
"""
import pathlib
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import torch
from ultralytics.yolo.utils.ops import xywh2xyxy

import wandb
from wandb import Image


def convert_to_wb_images(
    batch: Dict[str, Union[torch.Tensor, np.ndarray]],
    cls: Union[torch.Tensor, np.ndarray],
    bboxes: Union[torch.Tensor, np.ndarray],
    masks: Optional[Union[torch.Tensor, np.ndarray]],
    batch_idx: Union[torch.Tensor, np.ndarray],
    names: Dict[int, str],
) -> Tuple[List[Tuple[Image, Image]], List[Dict[Any, Union[float, Any]]]]:
    """Utility to convert a batch of images, bounding boxes and masks from YOLO validator to list of wandb.Image objects
    Additionally, returns a list of dictionaries with the average confidences for each class
    """
    images = batch["img"]
    captions = batch["im_file"]
    if isinstance(images, torch.Tensor):
        images = images.cpu().float().numpy()
    if isinstance(cls, torch.Tensor):
        cls = cls.cpu().numpy()
    if isinstance(bboxes, torch.Tensor):
        bboxes = bboxes.cpu().numpy()
    if isinstance(masks, torch.Tensor):
        masks = masks.cpu().numpy().astype(int)
    if isinstance(batch_idx, torch.Tensor):
        batch_idx = batch_idx.cpu().numpy()

    if np.max(images[0]) <= 1:
        images *= 255  # de-normalise (optional)

    out_images = []
    class_set = wandb.Classes([{"name": v, "id": int(k)} for k, v in names.items()])

    bs, _, h, w = images.shape
    scores_data = []
    for i in range(len(images)):
        if len(cls) > 0:
            img = images[i].transpose(1, 2, 0)
            image_kwargs = {
                "data_or_path": img,
                "caption": pathlib.Path(captions[i]).name,
            }
            prediction_boxes_data, prediction_masks_data = load_boxes_data(
                i, batch_idx, cls, bboxes, masks, names, h, w
            )
            ground_truth_boxes_data, ground_truth_masks_data = load_boxes_data(
                i,
                batch["batch_idx"].cpu().numpy(),
                batch["cls"].squeeze(-1).cpu().numpy(),
                batch["bboxes"].cpu().numpy(),
                batch["masks"].cpu().numpy()
                if batch.get("masks") is not None
                else None,
                names,
                h,
                w,
            )
            image_kwargs["boxes"] = {
                "predictions": {
                    "box_data": prediction_boxes_data,
                    "class_labels": names,
                },
                "ground_truth": {
                    "box_data": ground_truth_boxes_data,
                    "class_labels": names,
                },
            }
            if prediction_masks_data is not None:
                image_kwargs["masks"] = {
                    "predictions": {
                        "mask_data": prediction_masks_data,
                        "class_labels": names,
                    }
                }
            if ground_truth_masks_data is not None:
                image_kwargs["masks"]["ground_truth"] = {
                    "mask_data": ground_truth_masks_data,
                    "class_labels": names,
                }
            image_kwargs["classes"] = class_set
            object_confidences: Dict[str, Any] = {}
            for prediction_box in prediction_boxes_data:
                object_confidences[
                    prediction_box["box_caption"]
                ] = object_confidences.get(prediction_box["box_caption"], []) + [
                    prediction_box["scores"]["conf"]
                ]
            for key, value in object_confidences.items():
                object_confidences[key] = sum(value) / len(value)
            scores_data.append(object_confidences)
            ground_truth_kwargs = deepcopy(image_kwargs)
            ground_truth_kwargs["boxes"].pop("predictions")
            if ground_truth_kwargs.get("masks") is not None:
                ground_truth_kwargs["masks"].pop("predictions")
            # TODO: Consider removing ground truth from predictions
            # image_kwargs["boxes"].pop("ground_truth")
            # image_kwargs["masks"].pop("ground_truth")
            out_images.append(
                (
                    wandb.Image(**ground_truth_kwargs),
                    wandb.Image(**image_kwargs),
                )
            )

    return out_images, scores_data


def load_boxes_data(
    i: int,
    batch_idx: np.array,
    cls: np.array,
    bboxes: np.array,
    masks: np.array,
    names: Dict[int, str],
    h: int,
    w: int,
) -> Tuple[List[Dict[str, Any]], Optional[np.array]]:
    """Utility to parse and convert bounding boxes and masks from YOLO validator wandb.Image format"""
    boxes_data = []
    idx = batch_idx == i
    boxes = xywh2xyxy(bboxes[idx, :4]).T
    classes = cls[idx].astype("int")
    labels = bboxes.shape[1] == 4
    conf = None if labels else bboxes[idx, 4]
    if boxes.shape[1]:
        if boxes.max() <= 1.01:  # if normalized with tolerance 0.01
            boxes[[0, 2]] *= w  # scale to pixels
            boxes[[1, 3]] *= h
    for j, box in enumerate(boxes.T.tolist()):
        box_data: Dict[str, Any] = {
            "position": dict(zip(("minX", "minY", "maxX", "maxY"), box)),
            "domain": "pixel",
        }
        c = classes[j]
        box_data["class_id"] = int(c)
        box_data["box_caption"] = names[c] if names else str(c)
        if conf is not None:
            box_data["scores"] = {"conf": float(conf[j])}
        boxes_data.append(box_data)

    if masks is not None and len(masks):
        if idx.shape[0] == masks.shape[0]:  # overlap_masks=False
            image_masks = masks[idx]
        else:  # overlap_masks=True
            image_masks = masks[[i]]  # (1, 640, 640)
            nl = idx.sum()
            index = np.arange(nl).reshape(nl, 1, 1) + 1
            image_masks = np.repeat(image_masks, nl, axis=0)
            image_masks = np.where(image_masks == index, 1.0, 0.0)
        image_mask = np.ones(shape=image_masks.shape[1:]) * -1
        for j, _ in enumerate(boxes.T.tolist()):
            if labels or (conf is not None and conf[j] > 0.25):
                mask = image_masks[j].astype(np.bool_)
                image_mask[np.where(mask)] = classes[j]
        mh, mw = image_mask.shape
        image_mask = image_mask.astype(np.uint8)
        if mh != h or mw != w:
            image_mask = cv2.resize(image_mask, (w, h))
        return boxes_data, image_mask
    return boxes_data, None
