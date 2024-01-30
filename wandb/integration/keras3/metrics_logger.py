from typing import Any, Dict, Literal, Optional, Union

import keras
from keras.callbacks import Callback

import wandb
from wandb.util import get_module

LogStrategy = Literal["epoch", "batch"]


class WandbMetricsLogger(Callback):
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
        try:
            if isinstance(self.model.optimizer, keras.optimizers.Optimizer):
                return float(self.model.optimizer.learning_rate.numpy().item())
        except Exception:
            if keras.backend.backend() == "torch":
                torch = get_module("torch")
                if isinstance(self.model.optimizer.learning_rate, torch.Tensor):
                    lr = self.model.optimizer.learning_rate.to("cpu")
                    return float(lr.numpy().item())
                else:
                    wandb.termerror("Unable to log learning rate.", repeat=False)
                    return None
            if keras.backend.backend() == "jax":
                try:
                    np = get_module("numpy")
                    return float(np.array(self.model.optimizer.learning_rate).item())
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
