from typing import List
from ultralytics.yolo.v8.classify.train import ClassificationTrainer
from ultralytics.yolo.engine.trainer import BaseTrainer
from ultralytics.yolo.utils.torch_utils import get_flops, get_num_params
from ultralytics.yolo.engine.model import YOLO
import wandb


class WandbLogger:
    """
    A YOLO model wrapper that tracks metrics, and logs models to Weights & Biases.
    Usage:
    ```python
    from wandb.integration.yolov8 import WandbLogger
    model = YOLO("yolov8n.pt")
    with WandbLogger(model,) as wb_model:
        wb_model.train(data="coco128.yaml", epochs=3, imgsz=640,)
    ```
    """

    def __init__(
        self,
        yolo: YOLO,
        run_name: str = None,
        project: str = None,
        tags: List[str] = None,
        resume: str = "allow",
    ):
        """
        A callback that logs metrics to Weights & Biases.
        Args:
            yolo: A YOLOv8 model that's inherited from `:class:ultralytics.yolo.engine.model.YOLO`
        """
        self.yolo = yolo
        self.run = None
        self.run_name = run_name
        self.project = project
        self.tags = tags
        self.resume = resume

        # [TODO]: ADD telemetry to track usage of this integration

    def on_pretrain_routine_start(self, trainer: BaseTrainer):
        """
        Starts a new wandb run to track the training process and log to Weights & Biases.

        Args:
            trainer: A task trainer that's inherited from `:class:ultralytics.yolo.engine.trainer.BaseTrainer`
                    that contains the model training and optimization routine.
        """

        if self.run is None:
            if wandb.run is None:
                self.run = wandb.init(
                    name=trainer.args.name or self.run_name,
                    project=trainer.args.project or self.project or "YOLOv8",
                    tags=["YOLOv8"] or self.tags,
                    config=vars(trainer.args),
                    resume="allow" or self.resume,
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

    def on_train_epoch_start(self, trainer: BaseTrainer):
        """
        On train epoch start we only log epoch number to the Weights & Biases run
        """
        # We log the epoch number here to commit the previous step,
        self.run.log({"epoch": trainer.epoch + 1})

    def on_train_epoch_end(self, trainer: BaseTrainer):
        """
        On train epoch end we log all the metrics to the Weights & Biases run.
        """
        self.run.log(
            {
                **trainer.metrics,
                **trainer.label_loss_items(trainer.tloss, prefix="train"),
                **trainer.lr,
            },
        )
        if not isinstance(trainer, ClassificationTrainer):
            self.run.log(
                {
                    "train_batch_images": [
                        wandb.Image(str(image_path), caption=image_path.stem)
                        for image_path in trainer.save_dir.glob("train_batch*.jpg")
                    ]
                }
            )

    def on_fit_epoch_end(self, trainer: BaseTrainer):
        """
        On fit epoch end we log all the best metrics and model detail to Weights & Biases run summary.
        """
        if trainer.epoch == 0:
            self.run.summary.update(
                {
                    "model/parameters": get_num_params(trainer.model),
                    "model/GFLOPs": round(get_flops(trainer.model), 3),
                    "model/speed(ms/img)": round(trainer.validator.speed[1], 3),
                }
            )

        if trainer.best_fitness == trainer.fitness:
            self.run.summary.update(
                {
                    "best/epoch": trainer.epoch + 1,
                    **{f"best/{key}": val for key, val in trainer.metrics.items()},
                }
            )

    def on_train_end(self, trainer: BaseTrainer):
        """
        On train end we log all the media, including plots, images and best model artifact to Weights & Biases.
        """
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
                name=f"{self.run.name}_model_best.pt",
                aliases=["best_model"],
            )

    def on_model_save(self, trainer: BaseTrainer):
        """
        On model save we log the model as an artifact to Weights & Biases.
        """
        self.run.log_artifact(
            str(trainer.last),
            type="model",
            name=f"{self.run.name}_model_last.pt",
            aliases=["last_model"],
        )

    def teardown(self, _trainer: BaseTrainer):
        """
        On teardown we finish the Weights & Biases run and set it to None.
        """
        self.run.finish()
        self.run = None

    @property
    def callbacks(
        self,
    ):
        """
        Contains all the relevant callbacks to add to the YOLO model for the Weights & Biases logging.
        """
        return {
            "on_pretrain_routine_start": self.on_pretrain_routine_start,
            "on_train_epoch_start": self.on_train_epoch_start,
            "on_train_epoch_end": self.on_train_epoch_end,
            "on_fit_epoch_end": self.on_fit_epoch_end,
            "on_train_end": self.on_train_end,
            "teardown": self.teardown,
        }

    def __enter__(self):
        """
        On enter we add all the callbacks to the YOLO model and return it.
        """
        for event, fn in self.callbacks.items():
            self.yolo.add_callback(event, fn)
        return self.yolo

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        On exit, we check if the run is still active and close it if necessary.
        """
        if self.run is not None:
            self.run.finish()
