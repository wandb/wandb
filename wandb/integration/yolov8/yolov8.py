from typing import Union

import wandb

from ultralytics.yolo.v8.detect.train import DetectionTrainer
from ultralytics.yolo.v8.detect.predict import DetectionPredictor

from .bbox_utils import get_ground_truth_annotations, create_prediction_metadata_map


def plot_bboxes(trainer: Union[DetectionTrainer, DetectionPredictor]):
    if isinstance(trainer, DetectionTrainer):
        dataloader = trainer.validator.dataloader
        class_label_map = trainer.validator.names
        predictions_metadata_map = create_prediction_metadata_map(
            trainer.validator.jdict
        )
        class_label_dict = {
            idx: class_label_map[idx] for idx in range(len(class_label_map))
        }
        images = []
        for batch_idx, batch in enumerate(dataloader):
            for img_idx, image_path in enumerate(batch["im_file"]):
                try:
                    ground_truth_data = get_ground_truth_annotations(
                        img_idx, image_path, batch, class_label_map
                    )
                    images.append(
                        wandb.Image(
                            image_path,
                            boxes={
                                "ground_truth": {
                                    "box_data": ground_truth_data,
                                    "class_labels": class_label_dict,
                                }
                            },
                        )
                    )
                except TypeError:
                    pass
            if batch_idx + 1 == 1:
                break
        wandb.log({"ground_truth": images}, commit=False)

    elif isinstance(trainer, DetectionPredictor):
        predictor = trainer
        results = predictor.results
        table = wandb.Table(columns=["Image", "Num-Objects", "Mean-Confidence"])
        for idx, result in enumerate(results):
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

        wandb.log({"Object-Detection-Table": table})
