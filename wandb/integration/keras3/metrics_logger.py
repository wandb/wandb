from typing import Any, Dict, Literal, Optional, Union

import keras
from keras.callbacks import Callback
from packaging import version

import wandb
from wandb.util import get_module

LogStrategy = Literal["epoch", "batch"]


class WandbMetricsLogger(Callback):
    """Logger that sends system metrics to W&B.

    `WandbMetricsLogger` automatically logs the `logs` dictionary that callback methods
    take as argument to wandb. The callback works for both [Keras3](https://keras.io/api/)
    and [Keras2](https://keras.io/2.15/api/) or `tf.keras`.

    Example:
        ```python
        from wandb.integration.keras3 import WandbMetricsLogger

        model.fit(
            X_train,
            y_train,
            validation_data=(X_test, y_test),
            callbacks=[WandbCallback()],
        )
        ```

    This callback automatically logs the following to a W&B run page:
    * system (CPU/GPU/TPU) metrics,
    * train and validation metrics defined in `model.compile`,
    * learning rate (both for a fixed value or a learning rate scheduler)

    Notes:
    If you resume training by passing `initial_epoch` to `model.fit` and you are using a
    learning rate scheduler, make sure to pass `initial_global_step` to
    `WandbMetricsLogger`. The `initial_global_step` is `step_size * initial_step`, where
    `step_size` is number of training steps per epoch. `step_size` can be calculated as
    the product of the cardinality of the training dataset and the batch size.

    Arguments:
        log_freq: ("epoch", "batch", or int) if "epoch", logs metrics
            at the end of each epoch. If "batch", logs metrics at the end
            of each batch. If an integer, logs metrics at the end of that
            many batches. Defaults to "epoch".
        initial_global_step: (int) Use this argument to correcly log the
            learning rate when you resume training from some `initial_epoch`,
            and a learning rate scheduler is used. This can be computed as
            `step_size * initial_step`. Defaults to 0.
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

        wandb.config.update({"keras_backend": keras.backend.backend()})

        log_freq = 1 if log_freq == "batch" else log_freq

        self.logging_batch_wise = isinstance(log_freq, int)
        self.log_freq: Any = log_freq if self.logging_batch_wise else None
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
        if version.parse(keras.__version__) > version.parse("3.0.0"):
            if isinstance(self.model.optimizer, keras.optimizers.Optimizer):
                return keras.ops.convert_to_numpy(self.model.optimizer.learning_rate)
        else:
            tf = get_module("tensorflow")
            if isinstance(self.model.optimizer.learning_rate, tf.Variable):
                return float(self.model.optimizer.learning_rate.numpy().item())
            try:
                return float(
                    self.model.optimizer.learning_rate(step=self.global_step)
                    .numpy()
                    .item()
                )
            except Exception:
                wandb.termerror("Unable to log learning rate.", repeat=False)
                return None

    def on_epoch_end(self, epoch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        logs = dict() if logs is None else {f"epoch/{k}": v for k, v in logs.items()}

        logs["epoch/epoch"] = epoch

        lr = self._get_lr()
        if lr is not None:
            logs["epoch/learning_rate"] = lr

        wandb.log(logs)

    def on_batch_end(self, batch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        self.global_step += 1
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
        self.on_batch_end(batch, logs if logs else {})
