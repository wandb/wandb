import sys
from typing import Any, Dict, List, Optional, Union

import tensorflow as tf  # type: ignore
from tensorflow.keras import callbacks  # type: ignore

import wandb
from wandb.integration.keras.keras import (
    patch_tf_keras,
    _CustomOptimizer,
    _GradAccumulatorCallback,
)
from wandb.sdk.lib import telemetry

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


LogStrategy = Literal["epoch", "batch"]


tf_logger = tf.get_logger()
patch_tf_keras()


class WandbMetricsLogger(callbacks.Callback):
    """`WandbMetricsLogger` automatically logs the `logs` dictionary
    that callback methods take as argument to wandb.

    This callback automatically logs the following to a W&B run page:
    * system (CPU/GPU/TPU) metrics,
    * train and validation metrics defined in `model.compile`,
    * learning rate (both for a fixed value or a learning rate scheduler)

    Notes:
    If you resume training by passing `initial_epoch` to `model.fit` and
    you are using a learning rate scheduler, make sure to pass
    `initial_global_step` to `WandbMetricsLogger`. The `initial_global_step`
    is `step_size * initial_step`, where `step_size` is number of training
    steps per epoch. `step_size` can be calculated as the product of the
    cardinality of the training dataset and the batch size.

    Arguments:
        log_freq ("epoch", "batch", or int): if "epoch", logs metrics
            at the end of each epoch. If "batch", logs metrics at the end
            of each batch. If an integer, logs metrics at the end of that
            many batches. Defaults to "epoch".
        initial_global_step (int): Use this argument to correcly log the
            learning rate when you resume training from some `initial_epoch`,
            and a learning rate scheduler is used. This can be computed as
            `step_size * initial_step`. Defaults to 0.
        backward_compatible (bool): Make logging backward compatible with
            `wandb.keras.WandbCallback`.
    """

    def __init__(
        self,
        log_freq: Union[LogStrategy, int] = "epoch",
        initial_global_step: int = 0,
        input_specs: Optional[List[Any]] = None,
        backward_compatible: bool = False,
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

        if log_freq == "batch":
            log_freq = 1

        self.logging_batch_wise = isinstance(log_freq, int)
        self.log_freq: Any = log_freq if self.logging_batch_wise else None
        self.global_batch = 0
        self.global_step = initial_global_step
        self.input_specs = input_specs
        self.backward_compatible = backward_compatible

        self.gradient_logging_possibility = self._check_gradient_logging_possibility()

        if not self.backward_compatible:
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

    def _check_gradient_logging_possibility(self):
        if self.input_specs is None:
            self.input_specs = self.model.inputs
            if self.input_specs in [None, []]:
                raise ValueError(
                    "Please provide the input specs to the WandGradientLogger callback."
                )
            else:
                return True
        else:
            return True

    def _build_grad_accumulator_model(self):
        inputs = self.model.inputs
        outputs = self.model(inputs)
        grad_acc_model = tf.keras.models.Model(inputs, outputs)
        grad_acc_model.compile(loss=self.model.loss, optimizer=_CustomOptimizer())

        # make sure magic doesn't think this is a user model
        grad_acc_model._wandb_internal_model = True

        self._grad_accumulator_model = grad_acc_model
        self._grad_accumulator_callback = _GradAccumulatorCallback()

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

    def _get_gradient_logs(self):
        # Suppress callback warnings grad accumulator
        og_level = tf_logger.level
        tf_logger.setLevel("ERROR")

        self._grad_accumulator_model.fit(
            self._training_data_x,
            self._training_data_y,
            verbose=0,
            callbacks=[self._grad_accumulator_callback],
        )
        tf_logger.setLevel(og_level)
        weights = self.model.trainable_weights
        grads = self._grad_accumulator_callback.grads
        metrics = {}
        for weight, grad in zip(weights, grads):
            metrics[
                "gradients/" + weight.name.split(":")[0] + ".gradient"
            ] = wandb.Histogram(grad)
        return metrics

    def set_model(self, model):
        super().set_model(model)
        self._build_grad_accumulator_model()

    def on_epoch_end(self, epoch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        """Called at the end of an epoch."""
        if self.backward_compatible:
            logs = dict() if logs is None else logs
        else:
            logs = (
                dict() if logs is None else {f"epoch/{k}": v for k, v in logs.items()}
            )

        if self.gradient_logging_possibility:
            gradient_logs = self._get_gradient_logs()
            logs = dict(logs.items() + gradient_logs.items())

        if self.backward_compatible:
            logs["epoch"] = epoch
        else:
            logs["epoch/epoch"] = epoch

        lr = self._get_lr()
        if lr is not None:
            if self.backward_compatible:
                logs["learning_rate"] = lr
            else:
                logs["epoch/learning_rate"] = lr

        if self.backward_compatible:
            if not self.logging_batch_wise:
                wandb.log(logs)
        else:
            wandb.log(logs)

    def on_batch_end(self, batch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        self.global_step += 1
        """An alias for `on_train_batch_end` for backwards compatibility."""
        if self.logging_batch_wise and batch % self.log_freq == 0:
            if self.backward_compatible:
                logs = dict() if logs is None else logs
            else:
                logs = (
                    dict()
                    if logs is None
                    else {f"batch/{k}": v for k, v in logs.items()}
                )

            if self.backward_compatible:
                logs["batch_step"] = self.global_batch
            else:
                logs["batch/batch_step"] = self.global_batch

            lr = self._get_lr()
            if lr is not None:
                if self.backward_compatible:
                    logs["learning_rate"] = lr
                else:
                    logs["batch/learning_rate"] = lr

            wandb.log(logs)

            self.global_batch += self.log_freq

    def on_train_batch_end(
        self, batch: int, logs: Optional[Dict[str, Any]] = None
    ) -> None:
        """Called at the end of a training batch in `fit` methods."""
        self.on_batch_end(batch, logs if logs else {})
