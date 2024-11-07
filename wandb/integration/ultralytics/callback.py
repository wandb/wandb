import copy
from datetime import datetime
from typing import Callable, Dict, Optional, Union

from packaging import version

try:
    import dill as pickle
except ImportError:
    import pickle

import wandb
from wandb.sdk.lib import telemetry

try:
    import torch
    import ultralytics
    from tqdm.auto import tqdm

    if version.parse(ultralytics.__version__) > version.parse("8.0.238"):
        wandb.termwarn(
            """This integration is tested and supported for ultralytics v8.0.238 and below.
            Please report any issues to https://github.com/wandb/wandb/issues with the tag `yolov8`.""",
            repeat=False,
        )

    from ultralytics.models import YOLO
    from ultralytics.models.sam.predict import Predictor as SAMPredictor
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

    try:
        from ultralytics.yolo.utils import RANK, __version__
    except ModuleNotFoundError:
        from ultralytics.utils import RANK, __version__

    from wandb.integration.ultralytics.bbox_utils import (
        plot_bbox_predictions,
        plot_detection_validation_results,
    )
    from wandb.integration.ultralytics.classification_utils import (
        plot_classification_predictions,
        plot_classification_validation_results,
    )
    from wandb.integration.ultralytics.mask_utils import (
        plot_mask_predictions,
        plot_sam_predictions,
        plot_segmentation_validation_results,
    )
    from wandb.integration.ultralytics.pose_utils import (
        plot_pose_predictions,
        plot_pose_validation_results,
    )
except Exception as e:
    wandb.Error(e)


TRAINER_TYPE = Union[
    ClassificationTrainer, DetectionTrainer, SegmentationTrainer, PoseTrainer
]
VALIDATOR_TYPE = Union[
    ClassificationValidator, DetectionValidator, SegmentationValidator, PoseValidator
]
PREDICTOR_TYPE = Union[
    ClassificationPredictor,
    DetectionPredictor,
    SegmentationPredictor,
    PosePredictor,
    SAMPredictor,
]


class WandBUltralyticsCallback:
    """Stateful callback for logging to W&B.

    In particular, it will log model checkpoints, predictions, and
    ground-truth annotations with interactive overlays for bounding boxes
    to Weights & Biases Tables during training, validation and prediction
    for a `ultratytics` workflow.

    Example:
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
        model: (ultralytics.yolo.engine.model.YOLO) YOLO Model of type
            `ultralytics.yolo.engine.model.YOLO`.
        epoch_logging_interval: (int) interval to log the prediction visualizations
            during training.
        max_validation_batches: (int) maximum number of validation batches to log to
            a table per epoch.
        enable_model_checkpointing: (bool) enable logging model checkpoints as
            artifacts at the end of eveny epoch if set to `True`.
        visualize_skeleton: (bool) visualize pose skeleton by drawing lines connecting
            keypoints for human pose.
    """

    def __init__(
        self,
        model: YOLO,
        epoch_logging_interval: int = 1,
        max_validation_batches: int = 1,
        enable_model_checkpointing: bool = False,
        visualize_skeleton: bool = False,
    ) -> None:
        self.epoch_logging_interval = epoch_logging_interval
        self.max_validation_batches = max_validation_batches
        self.enable_model_checkpointing = enable_model_checkpointing
        self.visualize_skeleton = visualize_skeleton
        self.task = model.task
        self.task_map = model.task_map
        self.model_name = (
            model.overrides["model"].split(".")[0]
            if "model" in model.overrides
            else None
        )
        self._make_tables()
        self._make_predictor(model)
        self.supported_tasks = ["detect", "segment", "pose", "classify"]
        self.prompts = None
        self.run_id = None
        self.train_epoch = None

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
        self.predictor = self.task_map[self.task]["predictor"](overrides=overrides)
        self.predictor.callbacks = {}
        self.predictor.args.save = False
        self.predictor.args.save_txt = False
        self.predictor.args.save_crop = False
        self.predictor.args.verbose = None

    def _save_model(self, trainer: TRAINER_TYPE):
        model_checkpoint_artifact = wandb.Artifact(f"run_{wandb.run.id}_model", "model")
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
        self.run_id = wandb.run.id

    @torch.no_grad()
    def on_fit_epoch_end(self, trainer: DetectionTrainer):
        if self.task in self.supported_tasks and self.train_epoch != trainer.epoch:
            self.train_epoch = trainer.epoch
            if (self.train_epoch + 1) % self.epoch_logging_interval == 0:
                validator = trainer.validator
                dataloader = validator.dataloader
                class_label_map = validator.names
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
                    self.train_validation_table = plot_segmentation_validation_results(
                        dataloader=dataloader,
                        class_label_map=class_label_map,
                        model_name=self.model_name,
                        predictor=self.predictor,
                        table=self.train_validation_table,
                        max_validation_batches=self.max_validation_batches,
                        epoch=trainer.epoch,
                    )
                elif self.task == "detect":
                    self.train_validation_table = plot_detection_validation_results(
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
            trainer.model.to(self.device)

    def on_train_end(self, trainer: TRAINER_TYPE):
        if self.task in self.supported_tasks:
            wandb.log({"Train-Table": self.train_validation_table}, commit=False)

    def on_val_start(self, validator: VALIDATOR_TYPE):
        wandb.run or wandb.init(
            project=validator.args.project or "YOLOv8",
            job_type="validation_" + validator.args.task,
        )

    @torch.no_grad()
    def on_val_end(self, trainer: VALIDATOR_TYPE):
        if self.task in self.supported_tasks:
            validator = trainer
            dataloader = validator.dataloader
            class_label_map = validator.names
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
                self.validation_table = plot_segmentation_validation_results(
                    dataloader=dataloader,
                    class_label_map=class_label_map,
                    model_name=self.model_name,
                    predictor=self.predictor,
                    table=self.validation_table,
                    max_validation_batches=self.max_validation_batches,
                )
            elif self.task == "detect":
                self.validation_table = plot_detection_validation_results(
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
            wandb.log({"Validation-Table": self.validation_table}, commit=False)

    def on_predict_start(self, predictor: PREDICTOR_TYPE):
        wandb.run or wandb.init(
            project=predictor.args.project or "YOLOv8",
            config=vars(predictor.args),
            job_type="prediction_" + predictor.args.task,
        )
        if isinstance(predictor, SAMPredictor):
            self.prompts = copy.deepcopy(predictor.prompts)
            self.prediction_table = wandb.Table(columns=["Image"])

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
                    if isinstance(predictor, SegmentationPredictor):
                        self.prediction_table = plot_mask_predictions(
                            result, self.model_name, self.prediction_table
                        )
                    elif isinstance(predictor, SAMPredictor):
                        self.prediction_table = plot_sam_predictions(
                            result, self.prompts, self.prediction_table
                        )
                elif self.task == "detect":
                    self.prediction_table = plot_bbox_predictions(
                        result, self.model_name, self.prediction_table
                    )
                elif self.task == "classify":
                    self.prediction_table = plot_classification_predictions(
                        result, self.model_name, self.prediction_table
                    )

            wandb.log({"Prediction-Table": self.prediction_table}, commit=False)

    @property
    def callbacks(self) -> Dict[str, Callable]:
        """Property contains all the relevant callbacks to add to the YOLO model for the Weights & Biases logging."""
        return {
            "on_train_start": self.on_train_start,
            "on_fit_epoch_end": self.on_fit_epoch_end,
            "on_train_end": self.on_train_end,
            "on_val_start": self.on_val_start,
            "on_val_end": self.on_val_end,
            "on_predict_start": self.on_predict_start,
            "on_predict_end": self.on_predict_end,
        }


# TODO: Add epoch interval
def add_wandb_callback(
    model: YOLO,
    epoch_logging_interval: int = 1,
    enable_model_checkpointing: bool = False,
    enable_train_validation_logging: bool = True,
    enable_validation_logging: bool = True,
    enable_prediction_logging: bool = True,
    max_validation_batches: Optional[int] = 1,
    visualize_skeleton: Optional[bool] = True,
):
    """Function to add the `WandBUltralyticsCallback` callback to the `YOLO` model.

    Example:
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
        model: (ultralytics.yolo.engine.model.YOLO) YOLO Model of type
            `ultralytics.yolo.engine.model.YOLO`.
        epoch_logging_interval: (int) interval to log the prediction visualizations
            during training.
        enable_model_checkpointing: (bool) enable logging model checkpoints as
            artifacts at the end of eveny epoch if set to `True`.
        enable_train_validation_logging: (bool) enable logging the predictions and
            ground-truths as interactive image overlays on the images from
            the validation dataloader to a `wandb.Table` along with
            mean-confidence of the predictions per-class at the end of each
            training epoch.
        enable_validation_logging: (bool) enable logging the predictions and
            ground-truths as interactive image overlays on the images from the
            validation dataloader to a `wandb.Table` along with
            mean-confidence of the predictions per-class at the end of
            validation.
        enable_prediction_logging: (bool) enable logging the predictions and
            ground-truths as interactive image overlays on the images from the
            validation dataloader to a `wandb.Table` along with mean-confidence
            of the predictions per-class at the end of each prediction.
        max_validation_batches: (Optional[int]) maximum number of validation batches to log to
            a table per epoch.
        visualize_skeleton: (Optional[bool]) visualize pose skeleton by drawing lines connecting
            keypoints for human pose.

    Returns:
        An instance of `ultralytics.yolo.engine.model.YOLO` with the `WandBUltralyticsCallback`.
    """
    if RANK in [-1, 0]:
        wandb_callback = WandBUltralyticsCallback(
            copy.deepcopy(model),
            epoch_logging_interval,
            max_validation_batches,
            enable_model_checkpointing,
            visualize_skeleton,
        )
        callbacks = wandb_callback.callbacks
        if not enable_train_validation_logging:
            _ = callbacks.pop("on_fit_epoch_end")
            _ = callbacks.pop("on_train_end")
        if not enable_validation_logging:
            _ = callbacks.pop("on_val_start")
            _ = callbacks.pop("on_val_end")
        if not enable_prediction_logging:
            _ = callbacks.pop("on_predict_start")
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
