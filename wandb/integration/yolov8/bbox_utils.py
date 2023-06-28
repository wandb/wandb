import wandb

from ultralytics.yolo.utils import RANK, ops
from ultralytics.yolo.engine.results import Results


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

    class_name_map_reverse = {v: k for k, v in class_name_map.items()}

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
                "class_id": class_name_map_reverse[label],
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


def plot_validation_results(dataloader, class_label_map):
    table = wandb.Table(columns=["Index", "Images"])
    images, data_idx = [], 0
    for batch_idx, batch in enumerate(dataloader):
        for img_idx, image_path in enumerate(batch["im_file"]):
            try:
                ground_truth_data = get_ground_truth_annotations(
                    img_idx, image_path, batch, class_label_map
                )
                wandb_image = wandb.Image(
                    image_path,
                    boxes={
                        "ground_truth": {
                            "box_data": ground_truth_data,
                            "class_labels": class_label_map,
                        }
                    },
                )
                table.add_data(data_idx, wandb_image)
                data_idx += 1
            except TypeError:
                pass
        if batch_idx + 1 == 1:
            break
    wandb.log({"Validation-Table": table})


def plot_predictions(result: Results, table: wandb.Table) -> wandb.Table:
    boxes = result.boxes.xywh.to("cpu").long().numpy()
    classes = result.boxes.cls.to("cpu").long().numpy()
    confidence = result.boxes.conf.to("cpu").numpy()
    class_id_to_label = {int(k): str(v) for k, v in result.names.items()}
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
    image = wandb.Image(result.orig_img[:, :, ::-1], boxes=boxes)
    table.add_data(image, len(box_data), total_confidence / len(box_data))
    return table
