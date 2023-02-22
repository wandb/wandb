from typing import List, Optional

from ultralytics.yolo.engine.model import YOLO
from ultralytics.yolo.engine.trainer import BaseTrainer
from ultralytics.yolo.utils import RANK
from ultralytics.yolo.utils.torch_utils import get_flops, get_num_params
from ultralytics.yolo.v8.classify.train import ClassificationTrainer

import wandb
from wandb.sdk.lib import telemetry


class WandbLogger:
    """
    A YOLO model wrapper that tracks metrics, and logs models to Weights & Biases.
    Usage:
    ```python
    from wandb.yolov8 import WandbLogger
    model = YOLO("yolov8n.pt")
    with WandbLogger(model,) as wb_model:
        wb_model.train(data="coco128.yaml", epochs=3, imgsz=640,)
    ```
    """

    def __init__(
        self,
        yolo: YOLO,
        run_name: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
        resume: Optional[str] = "allow",
        **kwargs,
    ):
        """
        A unitly class to manage wandb run and various callbacks for the ultralytics YOLOv8 framework.
        Args:
            yolo: A YOLOv8 model that's inherited from `:class:ultralytics.yolo.engine.model.YOLO`
            run_name: The name of the run to be created on Weights & Biases.
            project: The name of the project to be created on Weights & Biases.
            tags: A list of tags to be added to the run on Weights & Biases.
            resume: Whether to resume a previous run on Weights & Biases.
            **kwargs: Additional arguments to be passed to `wandb.init()`.
        """
        # TODO: Add a healthwarning to inform the user that this is in beta
        self.yolo = yolo
        self.run = None
        self.run_name = run_name
        self.project = project
        self.tags = tags
        self.resume = resume
        self.kwargs = kwargs

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
                    name=self.run_name if self.run_name else trainer.args.name,
                    project=self.project
                    if self.project
                    else trainer.args.project or "YOLOv8",
                    tags=self.tags if self.tags else ["YOLOv8"],
                    config=vars(trainer.args),
                    resume="allow" or self.resume,
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

    def on_pretrain_routine_end(self, trainer: BaseTrainer):
        """ """
        self.run.summary.update(
            {
                "model/parameters": get_num_params(trainer.model),
                "model/GFLOPs": round(get_flops(trainer.model), 3),
            }
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

        # TODO: consider getting additional metadata from the user
        if trainer.best.exists():
            self.run.log_artifact(
                str(trainer.best),
                type="model",
                name=f"{self.run.name}_{trainer.args.task}.pt",
                aliases=["best", f"epoch_{trainer.epoch + 1}"],
            )

    def on_model_save(self, trainer: BaseTrainer):
        """
        On model save we log the model as an artifact to Weights & Biases.
        """
        self.run.log_artifact(
            str(trainer.last),
            type="model",
            name=f"{self.run.name}_{trainer.args.task}.pt",
            aliases=["last", f"epoch_{trainer.epoch + 1}"],
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
            "on_pretrain_routine_end": self.on_pretrain_routine_end,
            "on_train_epoch_start": self.on_train_epoch_start,
            "on_train_epoch_end": self.on_train_epoch_end,
            "on_fit_epoch_end": self.on_fit_epoch_end,
            "on_train_end": self.on_train_end,
            "on_model_save": self.on_model_save,
            "teardown": self.teardown,
        }


def add_callbacks(
    yolo: YOLO,
    run_name: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    resume: Optional[str] = "allow",
    **kwargs,
) -> YOLO:
    """
    A YOLO model wrapper that tracks metrics, and logs models to Weights & Biases.
    Args:
        yolo: A YOLO inherited from `:class:ultralytics.yolo.engine.model.YOLO` to add the callbacks to.
        run_name: The name of the Weights & Biases run.
        project: The name of the Weights & Biases project.
        tags: A list of tags to add to the Weights & Biases run.
        resume: Whether to resume the Weights & Biases run if it exists.
        **kwargs: Additional arguments to pass to the `wandb.init()` method.

    Usage:
    ```python
    from wandb.yolov8 import add_callbacks
    model = YOLO("yolov8n.pt")
    model = add_callbacks(model,)
    model.train(data="coco128.yaml", epochs=3, imgsz=640,)
    ```
    """
    if RANK in [-1, 0]:
        wandb_logger = WandbLogger(
            yolo, run_name=run_name, project=project, tags=tags, resume=resume, **kwargs
        )
        for event, callback_fn in wandb_logger.callbacks.items():
            yolo.add_callback(event, callback_fn)
        return yolo
    else:
        wandb.termwarn(
            "Weights & Biases callbacks were not added to this instance of the "
            "model since the RANK of the process to add the callbacks was neither 0 or -1."
        )
    return yolo
