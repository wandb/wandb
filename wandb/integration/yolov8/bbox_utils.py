import wandb

from ultralytics.yolo.utils import RANK, ops


def scale_bounding_box_to_original_image_shape(
    box, resized_image_shape, original_image_shape, ratio_pad
):
    """
    YOLOv8 resizes images during training and the label values
    are normalized based on this resized shape. This function rescales the
    bounding box labels to the original image shape.

    Reference: https://github.com/ultralytics/ultralytics/blob/main/ultralytics/yolo/utils/callbacks/comet.py#L105
    """

    resized_image_height, resized_image_width = resized_image_shape

    # Convert normalized xywh format predictions to xyxy in resized scale format
    box = ops.xywhn2xyxy(box, h=resized_image_height, w=resized_image_width)
    # Scale box predictions from resized image scale back to original image scale
    box = ops.scale_boxes(resized_image_shape, box, original_image_shape, ratio_pad)
    # # Convert bounding box format from xyxy to xywh for Comet logging
    box = ops.xyxy2xywh(box)
    # # Adjust xy center to correspond top-left corner
    # box[:2] -= box[2:] / 2
    box = box.tolist()

    return box


def get_ground_truth_annotations(img_idx, image_path, batch, class_name_map=None):
    indices = batch["batch_idx"] == img_idx
    bboxes = batch["bboxes"][indices]
    cls_labels = batch["cls"][indices].squeeze(1).tolist()

    if len(bboxes) == 0:
        wandb.termwarn(f"Image: {image_path} has no bounding boxes labels")
        return None

    cls_labels = batch["cls"][indices].squeeze(1).tolist()
    if class_name_map:
        cls_labels = [str(class_name_map[label]) for label in cls_labels]

    original_image_shape = batch["ori_shape"][img_idx]
    resized_image_shape = batch["resized_shape"][img_idx]
    ratio_pad = batch["ratio_pad"][img_idx]

    original_image_shape = batch["ori_shape"][img_idx]
    resized_image_shape = batch["resized_shape"][img_idx]
    ratio_pad = batch["ratio_pad"][img_idx]

    data = []
    for box, label in zip(bboxes, cls_labels):
        box = scale_bounding_box_to_original_image_shape(
            box, resized_image_shape, original_image_shape, ratio_pad
        )
        data.append(
            {
                "position": {
                    "middle": [int(box[0]), int(box[1])],
                    "width": int(box[2]),
                    "height": int(box[3]),
                },
                "domain": "pixel",
                "class_id": cls_labels.index(label),
                "box_caption": label,
            }
        )

    return data


def create_prediction_metadata_map(model_predictions):
    """Create metadata map for model predictions by groupings them based on image ID."""
    pred_metadata_map = {}
    for prediction in model_predictions:
        pred_metadata_map.setdefault(prediction["image_id"], [])
        pred_metadata_map[prediction["image_id"]].append(prediction)

    return pred_metadata_map
