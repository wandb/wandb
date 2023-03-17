"""
Yolov8 integration for Weights & Biases
"""
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import torch
from ultralytics.yolo.engine.model import YOLO
from ultralytics.yolo.engine.trainer import BaseTrainer
from ultralytics.yolo.engine.validator import BaseValidator
from ultralytics.yolo.utils import RANK
from ultralytics.yolo.utils.plotting import output_to_target
from ultralytics.yolo.utils.torch_utils import get_flops, get_num_params
from ultralytics.yolo.v8.classify.train import ClassificationTrainer
from ultralytics.yolo.v8.detect import DetectionValidator
from ultralytics.yolo.v8.segment import SegmentationValidator

import wandb
from wandb.integration.yolov8.utils import convert_to_wb_images
from wandb.sdk.lib import telemetry


class WandbCallback:
    """An internal YOLO model wrapper that tracks metrics, and logs models to Weights & Biases.

    Usage:
    ```python
    from wandb.integration.yolov8.yolov8 import WandbCallback
    model = YOLO("yolov8n.pt")
    wandb_logger = WandbCallback(model,)
    for event, callback_fn in wandb_logger.callbacks.items():
        model.add_callback(event, callback_fn)
    ```
    """

    def __init__(
        self,
        yolo: YOLO,
        run_name: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
        resume: Optional[str] = None,
        **kwargs: Optional[Any],
    ) -> None:
        """A utility class to manage wandb run and various callbacks for the ultralytics YOLOv8 framework.

        Args:
            yolo: A YOLOv8 model that's inherited from `:class:ultralytics.yolo.engine.model.YOLO`
            run_name, str: The name of the Weights & Biases run, defaults to an auto generated run_name if `trainer.args.name` is not defined.
            project, str: The name of the Weights & Biases project, defaults to `"YOLOv8"` if `trainer.args.project` is not defined.
            tags, List[str]: A list of tags to be added to the Weights & Biases run, defaults to `["YOLOv8"]`.
            resume, str: Whether to resume a previous run on Weights & Biases, defaults to `None`.
            **kwargs: Additional arguments to be passed to `wandb.init()`.
        """
        self.yolo = yolo
        self.run_name = run_name
        self.project = project
        self.tags = tags
        self.resume = resume
        self.kwargs = kwargs
        self.og_plot_predictions: Union[None, Callable] = None
        self.validation_table: Union[None, wandb.Table] = None

    def on_pretrain_routine_start(self, trainer: BaseTrainer) -> None:
        """Starts a new wandb run to track the training process and log to Weights & Biases.

        Args:
            trainer: A task trainer that's inherited from `:class:ultralytics.yolo.engine.trainer.BaseTrainer`
                    that contains the model training and optimization routine.
        """
        if wandb.run is None:
            self.run = wandb.init(
                name=self.run_name if self.run_name else trainer.args.name,
                project=self.project
                if self.project
                else trainer.args.project or "YOLOv8",
                tags=self.tags if self.tags else ["YOLOv8"],
                config=vars(trainer.args),
                resume=self.resume if self.resume else None,
                **self.kwargs,
            )
        else:
            self.run = wandb.run
        self.run.define_metric("epoch", hidden=True)
        self.run.define_metric(
            "train/*", step_metric="epoch", step_sync=True, summary="min"
        )

        self.run.define_metric(
            "val/*", step_metric="epoch", step_sync=True, summary="min"
        )

        self.run.define_metric(
            "metrics/*", step_metric="epoch", step_sync=True, summary="max"
        )
        self.run.define_metric(
            "lr/*", step_metric="epoch", step_sync=True, summary="last"
        )

        with telemetry.context(run=wandb.run) as tel:
            tel.feature.ultralytics_yolov8 = True

    def on_pretrain_routine_end(self, trainer: BaseTrainer) -> None:
        self.run.summary.update(
            {
                "model/parameters": get_num_params(trainer.model),
                "model/GFLOPs": round(get_flops(trainer.model), 3),
            }
        )

    def on_train_epoch_start(self, trainer: BaseTrainer) -> None:
        """On train epoch start we only log epoch number to the Weights & Biases run."""
        # We log the epoch number here to commit the previous step,
        self.run.log({"epoch": trainer.epoch + 1})

    def on_train_epoch_end(self, trainer: BaseTrainer) -> None:
        """On train epoch end we log all the metrics to the Weights & Biases run."""
        self.run.log(
            {
                **trainer.metrics,
                **trainer.label_loss_items(trainer.tloss, prefix="train"),
                **trainer.lr,
            },
        )
        # Currently only the detection and segmentation trainers save images to the save_dir
        if not isinstance(trainer, ClassificationTrainer):
            self.run.log(
                {
                    "train_batch_images": [
                        wandb.Image(str(image_path), caption=image_path.stem)
                        for image_path in trainer.save_dir.glob("train_batch*.jpg")
                    ]
                }
            )

    def on_fit_epoch_end(self, trainer: BaseTrainer) -> None:
        """On fit epoch end we log all the best metrics and model detail to Weights & Biases run summary."""
        if trainer.epoch == 0:
            speeds = [
                trainer.validator.speed.get(
                    key,
                )
                for key in (1, "inference")
            ]
            speed = speeds[0] if speeds[0] else speeds[1]
            if speed:
                self.run.summary.update(
                    {
                        "model/speed(ms/img)": round(speed, 3),
                    }
                )
        if trainer.best_fitness == trainer.fitness:
            self.run.summary.update(
                {
                    "best/epoch": trainer.epoch + 1,
                    **{f"best/{key}": val for key, val in trainer.metrics.items()},
                }
            )

    def on_train_end(self, trainer: BaseTrainer) -> None:
        """On train end we log all the media, including plots, images and best model artifact to Weights & Biases."""
        # Currently only the detection and segmentation trainers save images to the save_dir
        if not isinstance(trainer, ClassificationTrainer):
            self.run.log(
                {
                    "plots": [
                        wandb.Image(str(image_path), caption=image_path.stem)
                        for image_path in trainer.save_dir.glob("*.png")
                    ],
                    "val_images": [
                        wandb.Image(str(image_path), caption=image_path.stem)
                        for image_path in trainer.validator.save_dir.glob("val*.jpg")
                    ],
                },
            )

        if trainer.best.exists():
            self.run.log_artifact(
                str(trainer.best),
                type="model",
                name=f"{self.run.name}_{trainer.args.task}.pt",
                aliases=["best", f"epoch_{trainer.epoch + 1}"],
            )

    def on_model_save(self, trainer: BaseTrainer) -> None:
        """On model save we log the model as an artifact to Weights & Biases."""
        self.run.log_artifact(
            str(trainer.last),
            type="model",
            name=f"{self.run.name}_{trainer.args.task}.pt",
            aliases=["last", f"epoch_{trainer.epoch + 1}"],
        )

    def teardown(self, _trainer: BaseTrainer) -> None:
        """On teardown, we finish the Weights & Biases run and set it to None."""
        self.run.finish()
        self.run = None

    def on_val_start(
        self,
        validator: BaseValidator,
    ) -> None:
        """On validation start we create a wandb table to store the sample predictions
        and patch the validator's `plot_predictions` method to plot the predictions to the wandb table .
        """
        class_names = sorted(validator.names.values())
        if isinstance(validator, DetectionValidator):
            self.validation_table = wandb.Table(
                columns=["Batch", "Ground Truth", "Prediction", *class_names]
            )
            self.og_plot_predictions = validator.plot_predictions
            validator.plot_predictions = partial(
                plot_detection_predictions, self, validator
            )

        if isinstance(validator, SegmentationValidator):
            self.validation_table = wandb.Table(
                columns=["Batch", "Ground Truth", "Prediction", *class_names]
            )
            self.og_plot_predictions = validator.plot_predictions
            validator.plot_predictions = partial(
                plot_segmentation_predictions, self, validator
            )

    def on_val_end(self, validator: BaseValidator) -> None:
        """On validation end we log the validation table and unpatch the validator's `plot_predictions` method."""
        if self.validation_table is not None:
            self.run.log({"sample_predictions": self.validation_table})
        if self.og_plot_predictions is not None:
            validator.plot_predictions = self.og_plot_predictions
            self.og_plot_predictions = None
            self.validation_table = None

    @property
    def callbacks(
        self,
    ) -> Dict[str, Callable]:
        """Property contains all the relevant callbacks to add to the YOLO model for the Weights & Biases logging."""
        return {
            "on_pretrain_routine_start": self.on_pretrain_routine_start,
            "on_pretrain_routine_end": self.on_pretrain_routine_end,
            "on_train_epoch_start": self.on_train_epoch_start,
            "on_train_epoch_end": self.on_train_epoch_end,
            "on_fit_epoch_end": self.on_fit_epoch_end,
            "on_train_end": self.on_train_end,
            "on_model_save": self.on_model_save,
            "teardown": self.teardown,
            "on_val_start": self.on_val_start,
            "on_val_end": self.on_val_end,
        }


def add_images_to_validation_table(
    logger: WandbCallback,
    validator: BaseValidator,
    images: List[Tuple[wandb.Image, wandb.Image]],
    scores: List[Dict[str, float]],
    batch_id: int,
) -> None:
    """Utility to add a wandb.Image, predictions and scores to the validation table"""
    objects = sorted(validator.names.values())
    for item in scores:
        for obj in objects:
            if obj not in item:
                item[obj] = 0.0
    for im, score in zip(
        images,
        scores,
    ):
        if logger.validation_table is not None:
            logger.validation_table.add_data(
                batch_id,
                *im,
                *map(lambda x: x[1], sorted(score.items(), key=lambda x: x[0])),
            )


def plot_detection_predictions(
    logger: WandbCallback,
    validator: BaseValidator,
    batch: Dict[str, Any],
    predictions: Any,
    batch_id: int,
) -> None:
    """Utility to plot predictions from the `DetectionValidator` to a wandb.Table"""
    (batch_idx, cls, bboxes) = output_to_target(predictions, max_det=15)
    wb_images, scores = convert_to_wb_images(
        batch=batch,
        batch_idx=batch_idx,
        cls=cls,
        bboxes=bboxes,
        masks=None,
        names=validator.names,
    )

    add_images_to_validation_table(logger, validator, wb_images, scores, batch_id)


def plot_segmentation_predictions(
    logger: WandbCallback,
    validator: BaseValidator,
    batch: Dict[str, Any],
    predictions: Any,
    ni: int,
) -> None:
    """Utility to plot predictions from the `SegmentationValidator` to a wandb.Table"""
    (batch_idx, cls, bboxes) = output_to_target(predictions[0], max_det=15)
    wb_images, scores = convert_to_wb_images(
        batch=batch,
        batch_idx=batch_idx,
        cls=cls,
        bboxes=bboxes,
        masks=torch.cat(validator.plot_masks, dim=0)
        if len(validator.plot_masks)
        else validator.plot_masks,
        names=validator.names,
    )
    validator.plot_masks.clear()
    add_images_to_validation_table(logger, validator, wb_images, scores, ni)


def add_callbacks(
    yolo: YOLO,
    run_name: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    resume: Optional[str] = None,
    **kwargs: Optional[Any],
) -> YOLO:
    """A YOLO model wrapper that tracks metrics, and logs models to Weights & Biases.

    Args:
        yolo: A YOLOv8 model that's inherited from `:class:ultralytics.yolo.engine.model.YOLO`
        run_name, str: The name of the Weights & Biases run, defaults to an auto generated name if `trainer.args.name` is not defined.
        project, str: The name of the Weights & Biases project, defaults to `"YOLOv8"` if `trainer.args.project` is not defined.
        tags, List[str]: A list of tags to be added to the Weights & Biases run, defaults to `["YOLOv8"]`.
        resume, str: Whether to resume a previous run on Weights & Biases, defaults to `None`.
        **kwargs: Additional arguments to be passed to `wandb.init()`.

    Usage:
    ```python
    from wandb.integration.yolov8 import add_callbacks as add_wandb_callbacks
    model = YOLO("yolov8n.pt")
    add_wandb_callbacks(model,)
    model.train(data="coco128.yaml", epochs=3, imgsz=640,)
    ```
    """
    wandb.termwarn(
        """The wandb callback is currently in beta and is subject to change based on updates to `ultralytics yolov8`.
        The callback is tested and supported for ultralytics v8.0.43 and above.
        Please report any issues to https://github.com/wandb/wandb/issues with the tag `yolov8`.
        """,
        repeat=False,
    )

    if RANK in [-1, 0]:
        wandb_logger = WandbCallback(
            yolo, run_name=run_name, project=project, tags=tags, resume=resume, **kwargs
        )
        for event, callback_fn in wandb_logger.callbacks.items():
            yolo.add_callback(event, callback_fn)
        return yolo
    else:
        wandb.termerror(
            "The RANK of the process to add the callbacks was neither 0 or -1."
            "No Weights & Biases callbacks were added to this instance of the YOLO model."
        )
    return yolo
