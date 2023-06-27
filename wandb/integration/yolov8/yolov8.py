import wandb

from ultralytics.yolo.v8.detect.train import DetectionTrainer

from .bbox_utils import get_ground_truth_annotations


def plot_bboxes(trainer: DetectionTrainer):
    if isinstance(trainer, DetectionTrainer):
        print("CALLBACK HERE!!!")
        dataloader = trainer.validator.dataloader
        class_label_map = trainer.validator.names
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
        wandb.log({"sample_images": images}, commit=False)
