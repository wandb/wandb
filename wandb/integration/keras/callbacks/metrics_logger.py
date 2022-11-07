import sys
from typing import Any, Dict, Optional, Union

import tensorflow as tf  # type: ignore
from tensorflow.keras import callbacks  # type: ignore

import wandb
from wandb.integration.keras.keras import patch_tf_keras
from wandb.sdk.lib import telemetry

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


LogStrategy = Literal["epoch", "batch"]


patch_tf_keras()


class WandbMetricsLogger(callbacks.Callback):
    """`WandbMetricsLogger` automatically logs the `logs` dictionary
    that callback methods take as argument to wandb.

    This callback logs all metrics to Weights & Biases workspace, including:
    * Metrics summary plots
    * System metrics plots
    * Learning rate (both for a fixed value or a learning rate scheduler)

    Note that,
    * If you are using the `WandbMetricsLogger` while you are resuming
    training after training for a certain number of epochs, you can set
    `initial_global_step` to the point in terms of global step from which
    training is being resumed, which would ideally be
    `step_size * initial_epoch`, while also setting the `initial_epoch`
    parameter in your `model.fit` call.
    * The `step_size` is the number of training steps per epoch. It could
    be calculated as the product of the cardinality of the training dataset
    and the batch size.

    Arguments:
        log_freq ("epoch", "batch", or int): if "epoch", logs metrics
            at the end of each epoch. If "batch", logs metrics at the end
            of each batch. If an integer, logs metrics at the end of that
            many batches. Defaults to "epoch".
        initial_global_step (int): The initial global step which is incremented
            on every train batch. This is set to `0` by default and should be
            ideally set to `step_size * initial_epoch`, where `step_size` is
            the number of training steps per epoch. The step_size could be
            calculated as the product of the cardinality of the training dataset
            and the batch size.
    """

    def __init__(
        self,
        log_freq: Union[LogStrategy, int] = "epoch",
        initial_global_step: int = 0,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)

        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before WandbMetricsLogger()"
            )

        with telemetry.context(run=wandb.run) as tel:
            tel.feature.keras_metrics_logger = True

        self.logging_batch_wise = False
        if log_freq == "batch" or isinstance(log_freq, int):
            self.logging_batch_wise = True
            if log_freq == "batch":
                self.log_freq = 1
            else:
                self.log_freq = log_freq

        self.global_batch = 0
        self.global_step = initial_global_step

        if self.logging_batch_wise:
            # define custom x-axis for batch logging.
            wandb.define_metric("batch/batch_step")
            # set all batch metrics to be logged against batch_step.
            wandb.define_metric("batch/*", step_metric="batch/batch_step")
        else:
            # define custom x-axis for epoch-wise logging.
            wandb.define_metric("epoch/epoch")
            # set all epoch-wise metrics to be logged against epoch.
            wandb.define_metric("epoch/*", step_metric="epoch/epoch")

    def _get_lr(self) -> Union[float, None]:
        if isinstance(self.model.optimizer.learning_rate, tf.Variable):
            return float(self.model.optimizer.learning_rate.numpy().item())
        try:
            return float(
                self.model.optimizer.learning_rate(step=self.global_step).numpy().item()
            )
        except Exception:
            wandb.termerror("Unable to log learning rate.", repeat=False)
            return None

    def on_epoch_end(self, epoch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        """Called at the end of an epoch."""
        logs = dict() if logs is None else {f"epoch/{k}": v for k, v in logs.items()}

        logs["epoch/epoch"] = epoch

        lr = self._get_lr()
        if lr is not None:
            logs["epoch/learning_rate"] = lr

        wandb.log(logs)

    def on_batch_end(self, batch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        self.global_step += 1
        """An alias for `on_train_batch_end` for backwards compatibility."""
        if self.logging_batch_wise and batch % self.log_freq == 0:
            logs = {f"batch/{k}": v for k, v in logs.items()} if logs else {}
            logs["batch/batch_step"] = self.global_batch

            lr = self._get_lr()
            if lr is not None:
                logs["batch/learning_rate"] = lr

            wandb.log(logs)

            self.global_batch += self.log_freq

    def on_train_batch_end(
        self, batch: int, logs: Optional[Dict[str, Any]] = None
    ) -> None:
        """Called at the end of a training batch in `fit` methods."""
        self.on_batch_end(batch, logs if logs else {})
