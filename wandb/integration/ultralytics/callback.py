import copy
from datetime import datetime
from typing import Callable, Dict, Optional

try:
    import dill as pickle
except ImportError:
    import pickle

import torch
from tqdm.auto import tqdm

try:
    from ultralytics.yolo.engine.model import TASK_MAP, YOLO
    from ultralytics.yolo.utils import RANK, __version__
    from ultralytics.yolo.utils.torch_utils import de_parallel
    from ultralytics.yolo.v8.detect.predict import DetectionPredictor
    from ultralytics.yolo.v8.detect.train import DetectionTrainer
    from ultralytics.yolo.v8.detect.val import DetectionValidator
except ImportError as e:
    print(e)

import wandb
from wandb.integration.ultralytics.bbox_utils import (
    plot_predictions,
    plot_validation_results,
)
from wandb.sdk.lib import telemetry


class WandBUltralyticsCallback:
    """Stateful callback for logging model checkpoints, predictions, and
    ground-truth annotations with interactive overlays for bounding boxes
    to Weights & Biases Tables during training, validation and prediction
    for a `ultratytics` workflow.

    **Usage:**

    ```python
    from ultralytics.yolo.engine.model import YOLO

    import wandb
    from wandb.yolov8 import add_wandb_callback

    # initialize wandb run
    wandb.init(project="YOLOv8")

    # initialize YOLO model
    model = YOLO("yolov8n.pt")

    # add wandb callback
    add_wandb_callback(
        model, max_validation_batches=2, enable_model_checkpointing=True
    )

    # train
    model.train(data="coco128.yaml", epochs=5, imgsz=640)

    # validate
    model.val()

    # perform inference
    model(['img1.jpeg', 'img2.jpeg'])
    ```

    Args:
        model: YOLO Model of type `:class:ultralytics.yolo.engine.model.YOLO`.
        max_validation_batches: maximum number of validation batches to log to
            a table per epoch.
        enable_model_checkpointing: enable logging model checkpoints as
            artifacts at the end of eveny epoch if set to `True`.
    """

    def __init__(
        self,
        model: YOLO,
        max_validation_batches: int = 1,
        enable_model_checkpointing: bool = False,
    ) -> None:
        self.max_validation_batches = max_validation_batches
        self.enable_model_checkpointing = enable_model_checkpointing
        self.train_validation_table = wandb.Table(
            columns=["Epoch", "Data-Index", "Batch-Index", "Image", "Mean-Confidence"]
        )
        self.validation_table = wandb.Table(
            columns=["Data-Index", "Batch-Index", "Image", "Mean-Confidence"]
        )
        self.prediction_table = wandb.Table(
            columns=["Image", "Num-Objects", "Mean-Confidence"]
        )
        self._make_predictor(model)

    def _make_predictor(self, model: YOLO):
        overrides = model.overrides.copy()
        overrides["conf"] = 0.1
        self.predictor = TASK_MAP[model.task][3](overrides=overrides, _callbacks=None)

    def _save_model(self, trainer: DetectionTrainer):
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

    def on_train_start(self, trainer: DetectionTrainer):
        with telemetry.context(run=wandb.run) as tel:
            tel.feature.ultralytics_yolov8 = True

    def on_fit_epoch_end(self, trainer: DetectionTrainer):
        if isinstance(trainer, DetectionTrainer):
            validator = trainer.validator
            dataloader = validator.dataloader
            class_label_map = validator.names
            with torch.no_grad():
                self.device = next(trainer.model.parameters()).device
                trainer.model.to("cpu")
                self.model = copy.deepcopy(trainer.model).eval().to(self.device)
                self.predictor.setup_model(model=self.model, verbose=False)
                self.train_validation_table = plot_validation_results(
                    dataloader=dataloader,
                    class_label_map=class_label_map,
                    predictor=self.predictor,
                    table=self.train_validation_table,
                    max_validation_batches=self.max_validation_batches,
                    epoch=trainer.epoch,
                )
            if self.enable_model_checkpointing:
                self._save_model(trainer)
            trainer.model.to(self.device)

    def on_train_end(self, trainer: DetectionTrainer):
        wandb.log({"Train-Validation-Table": self.train_validation_table})

    def on_val_end(self, trainer: DetectionValidator):
        if isinstance(trainer, DetectionValidator):
            validator = trainer
            dataloader = validator.dataloader
            class_label_map = validator.names
            with torch.no_grad():
                self.predictor.setup_model(model=self.model, verbose=False)
                self.validation_table = plot_validation_results(
                    dataloader=dataloader,
                    class_label_map=class_label_map,
                    predictor=self.predictor,
                    table=self.validation_table,
                    max_validation_batches=self.max_validation_batches,
                )
            wandb.log({"Validation-Table": self.validation_table})

    def on_predict_end(self, predictor: DetectionPredictor):
        if isinstance(predictor, DetectionPredictor):
            for result in tqdm(predictor.results):
                self.prediction_table = plot_predictions(result, self.prediction_table)
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
):
    """Function to add the `WandBUltralyticsCallback` callback to the `YOLO`
    model.

    **Usage:**

    ```python
    from ultralytics.yolo.engine.model import YOLO

    import wandb
    from wandb.yolov8 import add_wandb_callback

    # initialize wandb run
    wandb.init(project="YOLOv8")

    # initialize YOLO model
    model = YOLO("yolov8n.pt")

    # add wandb callback
    add_wandb_callback(
        model, max_validation_batches=2, enable_model_checkpointing=True
    )

    # train
    model.train(data="coco128.yaml", epochs=5, imgsz=640)

    # validate
    model.val()

    # perform inference
    model(['img1.jpeg', 'img2.jpeg'])
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
    """
    if RANK in [-1, 0]:
        wandb_callback = WandBUltralyticsCallback(
            copy.deepcopy(model), max_validation_batches, enable_model_checkpointing
        )
        if not enable_train_validation_logging:
            _ = wandb_callback.callbacks.pop("on_fit_epoch_end")
            _ = wandb_callback.callbacks.pop("on_train_end")
        if not enable_validation_logging:
            _ = wandb_callback.callbacks.pop("on_val_end")
        if not enable_prediction_logging:
            _ = wandb_callback.callbacks.pop("on_predict_end")
        for event, callback_fn in wandb_callback.callbacks.items():
            model.add_callback(event, callback_fn)
    else:
        wandb.termerror(
            "The RANK of the process to add the callbacks was neither 0 or "
            "-1. No Weights & Biases callbacks were added to this instance "
            "of the YOLO model."
        )
    return model
