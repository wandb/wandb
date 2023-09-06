import copy
from datetime import datetime
from typing import Callable, Dict, Optional, Union

try:
    import dill as pickle
except ImportError:
    import pickle

import wandb
from wandb.sdk.lib import telemetry

try:
    import torch
    from tqdm.auto import tqdm
    from ultralytics.models import YOLO
    from ultralytics.models.yolo.classify import (
        ClassificationPredictor,
        ClassificationTrainer,
        ClassificationValidator,
    )
    from ultralytics.models.yolo.detect import (
        DetectionPredictor,
        DetectionTrainer,
        DetectionValidator,
    )
    from ultralytics.models.yolo.pose import PosePredictor, PoseTrainer, PoseValidator
    from ultralytics.models.yolo.segment import (
        SegmentationPredictor,
        SegmentationTrainer,
        SegmentationValidator,
    )
    from ultralytics.utils.torch_utils import de_parallel
    from ultralytics.yolo.utils import RANK, __version__

    from wandb.integration.ultralytics.bbox_utils import (
        plot_predictions,
        plot_validation_results,
    )
    from wandb.integration.ultralytics.classification_utils import (
        plot_classification_predictions,
        plot_classification_validation_results,
    )
    from wandb.integration.ultralytics.mask_utils import (
        plot_mask_predictions,
        plot_mask_validation_results,
    )
    from wandb.integration.ultralytics.pose_utils import (
        plot_pose_predictions,
        plot_pose_validation_results,
    )
except ImportError as e:
    wandb.error(e)


TRAINER_TYPE = Union[
    ClassificationTrainer, DetectionTrainer, SegmentationTrainer, PoseTrainer
]
VALIDATOR_TYPE = Union[
    ClassificationValidator, DetectionValidator, SegmentationValidator, PoseValidator
]
PREDICTOR_TYPE = Union[
    ClassificationPredictor, DetectionPredictor, SegmentationPredictor, PosePredictor
]


class WandBUltralyticsCallback:
    """Stateful callback for logging to W&B.

    In particular, it will log model checkpoints, predictions, and
    ground-truth annotations with interactive overlays for bounding boxes
    to Weights & Biases Tables during training, validation and prediction
    for a `ultratytics` workflow.

    **Usage:**

    ```python
    from ultralytics.yolo.engine.model import YOLO
    from wandb.yolov8 import add_wandb_callback

    # initialize YOLO model
    model = YOLO("yolov8n.pt")

    # add wandb callback
    add_wandb_callback(model, max_validation_batches=2, enable_model_checkpointing=True)

    # train
    model.train(data="coco128.yaml", epochs=5, imgsz=640)

    # validate
    model.val()

    # perform inference
    model(["img1.jpeg", "img2.jpeg"])
    ```

    Args:
        model: YOLO Model of type `:class:ultralytics.yolo.engine.model.YOLO`.
        max_validation_batches: maximum number of validation batches to log to
            a table per epoch.
        enable_model_checkpointing: enable logging model checkpoints as
            artifacts at the end of eveny epoch if set to `True`.
        visualize_skeleton: visualize pose skeleton by drawing lines connecting
            keypoints for human pose.
    """

    def __init__(
        self,
        model: YOLO,
        max_validation_batches: int = 1,
        enable_model_checkpointing: bool = False,
        visualize_skeleton: bool = False,
    ) -> None:
        self.max_validation_batches = max_validation_batches
        self.enable_model_checkpointing = enable_model_checkpointing
        self.visualize_skeleton = visualize_skeleton
        self.task = model.task
        self.task_map = model.task_map
        self.model_name = model.overrides["model"].split(".")[0]
        self._make_tables()
        self._make_predictor(model)
        self.supported_tasks = ["detect", "segment", "pose", "classify"]

    def _make_tables(self):
        if self.task in ["detect", "segment"]:
            validation_columns = [
                "Data-Index",
                "Batch-Index",
                "Image",
                "Mean-Confidence",
                "Speed",
            ]
            train_columns = ["Epoch"] + validation_columns
            self.train_validation_table = wandb.Table(
                columns=["Model-Name"] + train_columns
            )
            self.validation_table = wandb.Table(
                columns=["Model-Name"] + validation_columns
            )
            self.prediction_table = wandb.Table(
                columns=[
                    "Model-Name",
                    "Image",
                    "Num-Objects",
                    "Mean-Confidence",
                    "Speed",
                ]
            )
        elif self.task == "classify":
            classification_columns = [
                "Image",
                "Predicted-Category",
                "Prediction-Confidence",
                "Top-5-Prediction-Categories",
                "Top-5-Prediction-Confindence",
                "Probabilities",
                "Speed",
            ]
            validation_columns = ["Data-Index", "Batch-Index"] + classification_columns
            validation_columns.insert(3, "Ground-Truth-Category")
            self.train_validation_table = wandb.Table(
                columns=["Model-Name", "Epoch"] + validation_columns
            )
            self.validation_table = wandb.Table(
                columns=["Model-Name"] + validation_columns
            )
            self.prediction_table = wandb.Table(
                columns=["Model-Name"] + classification_columns
            )
        elif self.task == "pose":
            validation_columns = [
                "Data-Index",
                "Batch-Index",
                "Image-Ground-Truth",
                "Image-Prediction",
                "Num-Instances",
                "Mean-Confidence",
                "Speed",
            ]
            train_columns = ["Epoch"] + validation_columns
            self.train_validation_table = wandb.Table(
                columns=["Model-Name"] + train_columns
            )
            self.validation_table = wandb.Table(
                columns=["Model-Name"] + validation_columns
            )
            self.prediction_table = wandb.Table(
                columns=[
                    "Model-Name",
                    "Image-Prediction",
                    "Num-Instances",
                    "Mean-Confidence",
                    "Speed",
                ]
            )

    def _make_predictor(self, model: YOLO):
        overrides = copy.deepcopy(model.overrides)
        overrides["conf"] = 0.1
        self.predictor = self.task_map[self.task]["predictor"](
            overrides=overrides, _callbacks=None
        )

    def _save_model(self, trainer: TRAINER_TYPE):
        model_checkpoint_artifact = wandb.Artifact(
            f"run_{wandb.run.id}_model", "model", metadata=vars(trainer.args)
        )
        checkpoint_dict = {
            "epoch": trainer.epoch,
            "best_fitness": trainer.best_fitness,
            "model": copy.deepcopy(de_parallel(self.model)).half(),
            "ema": copy.deepcopy(trainer.ema.ema).half(),
            "updates": trainer.ema.updates,
            "optimizer": trainer.optimizer.state_dict(),
            "train_args": vars(trainer.args),
            "date": datetime.now().isoformat(),
            "version": __version__,
        }
        checkpoint_path = trainer.wdir / f"epoch{trainer.epoch}.pt"
        torch.save(checkpoint_dict, checkpoint_path, pickle_module=pickle)
        model_checkpoint_artifact.add_file(checkpoint_path)
        wandb.log_artifact(
            model_checkpoint_artifact, aliases=[f"epoch_{trainer.epoch}"]
        )

    def on_train_start(self, trainer: TRAINER_TYPE):
        with telemetry.context(run=wandb.run) as tel:
            tel.feature.ultralytics_yolov8 = True
        wandb.config.train = vars(trainer.args)

    def on_fit_epoch_end(self, trainer: TRAINER_TYPE):
        if self.task in self.supported_tasks:
            validator = trainer.validator
            dataloader = validator.dataloader
            class_label_map = validator.names
            with torch.no_grad():
                self.device = next(trainer.model.parameters()).device
                if isinstance(trainer.model, torch.nn.parallel.DistributedDataParallel):
                    model = trainer.model.module
                else:
                    model = trainer.model
                self.model = copy.deepcopy(model).eval().to(self.device)
                self.predictor.setup_model(model=self.model, verbose=False)
                if self.task == "pose":
                    self.train_validation_table = plot_pose_validation_results(
                        dataloader=dataloader,
                        class_label_map=class_label_map,
                        model_name=self.model_name,
                        predictor=self.predictor,
                        visualize_skeleton=self.visualize_skeleton,
                        table=self.train_validation_table,
                        max_validation_batches=self.max_validation_batches,
                        epoch=trainer.epoch,
                    )
                elif self.task == "segment":
                    self.train_validation_table = plot_mask_validation_results(
                        dataloader=dataloader,
                        class_label_map=class_label_map,
                        model_name=self.model_name,
                        predictor=self.predictor,
                        table=self.train_validation_table,
                        max_validation_batches=self.max_validation_batches,
                        epoch=trainer.epoch,
                    )
                elif self.task == "detect":
                    self.train_validation_table = plot_validation_results(
                        dataloader=dataloader,
                        class_label_map=class_label_map,
                        model_name=self.model_name,
                        predictor=self.predictor,
                        table=self.train_validation_table,
                        max_validation_batches=self.max_validation_batches,
                        epoch=trainer.epoch,
                    )
                elif self.task == "classify":
                    self.train_validation_table = (
                        plot_classification_validation_results(
                            dataloader=dataloader,
                            model_name=self.model_name,
                            predictor=self.predictor,
                            table=self.train_validation_table,
                            max_validation_batches=self.max_validation_batches,
                            epoch=trainer.epoch,
                        )
                    )
            if self.enable_model_checkpointing:
                self._save_model(trainer)
            self.model.to("cpu")
            trainer.model.to(self.device)

    def on_train_end(self, trainer: TRAINER_TYPE):
        if self.task in self.supported_tasks:
            wandb.log({"Train-Validation-Table": self.train_validation_table})

    def on_val_end(self, trainer: VALIDATOR_TYPE):
        if self.task in self.supported_tasks:
            validator = trainer
            dataloader = validator.dataloader
            class_label_map = validator.names
            with torch.no_grad():
                self.model.to(self.device)
                self.predictor.setup_model(model=self.model, verbose=False)
                if self.task == "pose":
                    self.validation_table = plot_pose_validation_results(
                        dataloader=dataloader,
                        class_label_map=class_label_map,
                        model_name=self.model_name,
                        predictor=self.predictor,
                        visualize_skeleton=self.visualize_skeleton,
                        table=self.validation_table,
                        max_validation_batches=self.max_validation_batches,
                    )
                elif self.task == "segment":
                    self.validation_table = plot_mask_validation_results(
                        dataloader=dataloader,
                        class_label_map=class_label_map,
                        model_name=self.model_name,
                        predictor=self.predictor,
                        table=self.validation_table,
                        max_validation_batches=self.max_validation_batches,
                    )
                elif self.task == "detect":
                    self.validation_table = plot_validation_results(
                        dataloader=dataloader,
                        class_label_map=class_label_map,
                        model_name=self.model_name,
                        predictor=self.predictor,
                        table=self.validation_table,
                        max_validation_batches=self.max_validation_batches,
                    )
                elif self.task == "classify":
                    self.validation_table = plot_classification_validation_results(
                        dataloader=dataloader,
                        model_name=self.model_name,
                        predictor=self.predictor,
                        table=self.validation_table,
                        max_validation_batches=self.max_validation_batches,
                    )
            wandb.log({"Validation-Table": self.validation_table})

    def on_predict_end(self, predictor: PREDICTOR_TYPE):
        wandb.config.prediction_configs = vars(predictor.args)
        if self.task in self.supported_tasks:
            for result in tqdm(predictor.results):
                if self.task == "pose":
                    self.prediction_table = plot_pose_predictions(
                        result,
                        self.model_name,
                        self.visualize_skeleton,
                        self.prediction_table,
                    )
                elif self.task == "segment":
                    self.prediction_table = plot_mask_predictions(
                        result, self.model_name, self.prediction_table
                    )
                elif self.task == "detect":
                    self.prediction_table = plot_predictions(
                        result, self.model_name, self.prediction_table
                    )
                elif self.task == "classify":
                    self.prediction_table = plot_classification_predictions(
                        result, self.model_name, self.prediction_table
                    )

            wandb.log({"Prediction-Table": self.prediction_table})

    @property
    def callbacks(self) -> Dict[str, Callable]:
        """Property contains all the relevant callbacks to add to the YOLO model for the Weights & Biases logging."""
        return {
            "on_train_start": self.on_train_start,
            "on_fit_epoch_end": self.on_fit_epoch_end,
            "on_train_end": self.on_train_end,
            "on_val_end": self.on_val_end,
            "on_predict_end": self.on_predict_end,
        }


def add_wandb_callback(
    model: YOLO,
    enable_model_checkpointing: bool = False,
    enable_train_validation_logging: bool = True,
    enable_validation_logging: bool = True,
    enable_prediction_logging: bool = True,
    max_validation_batches: Optional[int] = 1,
    visualize_skeleton: Optional[bool] = True,
):
    """Function to add the `WandBUltralyticsCallback` callback to the `YOLO` model.

    **Usage:**

    ```python
    from ultralytics.yolo.engine.model import YOLO
    from wandb.yolov8 import add_wandb_callback

    # initialize YOLO model
    model = YOLO("yolov8n.pt")

    # add wandb callback
    add_wandb_callback(model, max_validation_batches=2, enable_model_checkpointing=True)

    # train
    model.train(data="coco128.yaml", epochs=5, imgsz=640)

    # validate
    model.val()

    # perform inference
    model(["img1.jpeg", "img2.jpeg"])
    ```

    Args:
        model: YOLO Model of type `:class:ultralytics.yolo.engine.model.YOLO`.
        enable_model_checkpointing: enable logging model checkpoints as
            artifacts at the end of eveny epoch if set to `True`.
        enable_train_validation_logging: enable logging the predictions and
            ground-truths as interactive image overlays on the images from
            the validation dataloader to a `wandb.Table` along with
            mean-confidence of the predictions per-class at the end of each
            training epoch.
        enable_validation_logging: enable logging the predictions and
            ground-truths as interactive image overlays on the images from the
            validation dataloader to a `wandb.Table` along with
            mean-confidence of the predictions per-class at the end of
            validation.
        enable_prediction_logging: enable logging the predictions and
            ground-truths as interactive image overlays on the images from the
            validation dataloader to a `wandb.Table` along with mean-confidence
            of the predictions per-class at the end of each prediction.
        max_validation_batches: maximum number of validation batches to log to
            a table per epoch.
        visualize_skeleton: visualize pose skeleton by drawing lines connecting
            keypoints for human pose.
    """
    if RANK in [-1, 0]:
        wandb_callback = WandBUltralyticsCallback(
            copy.deepcopy(model),
            max_validation_batches,
            enable_model_checkpointing,
            visualize_skeleton,
        )
        callbacks = wandb_callback.callbacks
        if not enable_train_validation_logging:
            _ = callbacks.pop("on_fit_epoch_end")
            _ = callbacks.pop("on_train_end")
        if not enable_validation_logging:
            _ = callbacks.pop("on_val_end")
        if not enable_prediction_logging:
            _ = callbacks.pop("on_predict_end")
        for event, callback_fn in callbacks.items():
            model.add_callback(event, callback_fn)
    else:
        wandb.termerror(
            "The RANK of the process to add the callbacks was neither 0 or "
            "-1. No Weights & Biases callbacks were added to this instance "
            "of the YOLO model."
        )
    return model
