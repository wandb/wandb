import sys
from typing import Any, Dict, Optional, Union

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

    It also logs the system metrics to wandb.

    Arguments:
        log_freq ("epoch", "batch", or int): if "epoch", logs metrics
            at the end of each epoch. If "batch", logs metrics at the end
            of each batch. If an integer, logs metrics at the end of that
            many batches. Defaults to "epoch".
    """

    def __init__(
        self, log_freq: Union[LogStrategy, int] = "epoch", *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)

        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before WandbMetricsLogger()"
            )

        with telemetry.context(run=wandb.run) as tel:
            tel.feature.keras_metrics_logger = True

        if log_freq == "batch":
            self.log_freq: Union[LogStrategy, int] = 1
        else:
            self.log_freq = log_freq
        self.global_batch = 0

        if isinstance(log_freq, int):
            # define custom x-axis for batch logging.
            wandb.define_metric("batch/batch_step")
            # set all batch metrics to be logged against batch_step.
            wandb.define_metric("batch/*", step_metric="batch/batch_step")

    def on_epoch_end(self, epoch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        """Called at the end of an epoch."""
        wandb.log({"epoch": epoch}, commit=False)
        wandb.log(logs or {}, commit=True)

    def on_batch_end(self, batch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        """An alias for `on_train_batch_end` for backwards compatibility."""
        if isinstance(self.log_freq, int) and batch % self.log_freq == 0:
            wandb.log({"batch/batch_step": self.global_batch}, commit=False)

            logs = {f"batch/{k}": v for k, v in logs.items()} if logs else {}
            wandb.log(logs, commit=True)

            self.global_batch += self.log_freq

    def on_train_batch_end(
        self, batch: int, logs: Optional[Dict[str, Any]] = None
    ) -> None:
        """Called at the end of a training batch in `fit` methods."""
        self.on_batch_end(batch, logs or {})
