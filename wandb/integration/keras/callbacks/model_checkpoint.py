import os
import string
from typing import Any, Dict, List, Literal, Optional, Union

import tensorflow as tf  # type: ignore
from tensorflow.keras import callbacks  # type: ignore

import wandb
from wandb.sdk.lib import telemetry
from wandb.sdk.lib.paths import StrPath

from ..keras import patch_tf_keras

Mode = Literal["auto", "min", "max"]
SaveStrategy = Literal["epoch"]

patch_tf_keras()


class WandbModelCheckpoint(callbacks.ModelCheckpoint):
    """A checkpoint that periodically saves a Keras model or model weights.

    Saved weights are uploaded to W&B as a `wandb.Artifact`.

    Since this callback is subclassed from `tf.keras.callbacks.ModelCheckpoint`, the
    checkpointing logic is taken care of by the parent callback. You can learn more
    here: https://www.tensorflow.org/api_docs/python/tf/keras/callbacks/ModelCheckpoint

    This callback is to be used in conjunction with training using `model.fit()` to save
    a model or weights (in a checkpoint file) at some interval. The model checkpoints
    will be logged as W&B Artifacts. You can learn more here:
    https://docs.wandb.ai/guides/artifacts

    This callback provides the following features:
        - Save the model that has achieved "best performance" based on "monitor".
        - Save the model at the end of every epoch regardless of the performance.
        - Save the model at the end of epoch or after a fixed number of training batches.
        - Save only model weights, or save the whole model.
        - Save the model either in SavedModel format or in `.h5` format.

    Args:
        filepath: (Union[str, os.PathLike]) path to save the model file. `filepath`
            can contain named formatting options, which will be filled by the value
            of `epoch` and keys in `logs` (passed in `on_epoch_end`). For example:
            if `filepath` is `model-{epoch:02d}-{val_loss:.2f}`, then the
            model checkpoints will be saved with the epoch number and the
            validation loss in the filename.
        monitor: (str) The metric name to monitor. Default to "val_loss".
        verbose: (int) Verbosity mode, 0 or 1. Mode 0 is silent, and mode 1
            displays messages when the callback takes an action.
        save_best_only: (bool) if `save_best_only=True`, it only saves when the model
            is considered the "best" and the latest best model according to the
            quantity monitored will not be overwritten. If `filepath` doesn't contain
            formatting options like `{epoch}` then `filepath` will be overwritten by
            each new better model locally. The model logged as an artifact will still be
            associated with the correct `monitor`.  Artifacts will be uploaded
            continuously and versioned separately as a new best model is found.
        save_weights_only: (bool) if True, then only the model's weights will be saved.
        mode: (Mode) one of {'auto', 'min', 'max'}. For `val_acc`, this should be `max`,
            for `val_loss` this should be `min`, etc.
        save_freq: (Union[SaveStrategy, int]) `epoch` or integer. When using `'epoch'`,
            the callback saves the model after each epoch. When using an integer, the
            callback saves the model at end of this many batches.
            Note that when monitoring validation metrics such as `val_acc` or `val_loss`,
            save_freq must be set to "epoch" as those metrics are only available at the
            end of an epoch.
        initial_value_threshold: (Optional[float]) Floating point initial "best" value of the metric
            to be monitored.
    """

    def __init__(
        self,
        filepath: StrPath,
        monitor: str = "val_loss",
        verbose: int = 0,
        save_best_only: bool = False,
        save_weights_only: bool = False,
        mode: Mode = "auto",
        save_freq: Union[SaveStrategy, int] = "epoch",
        initial_value_threshold: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            filepath=filepath,
            monitor=monitor,
            verbose=verbose,
            save_best_only=save_best_only,
            save_weights_only=save_weights_only,
            mode=mode,
            save_freq=save_freq,
            initial_value_threshold=initial_value_threshold,
            **kwargs,
        )
        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before `WandbModelCheckpoint()`"
            )
        with telemetry.context(run=wandb.run) as tel:
            tel.feature.keras_model_checkpoint = True

        self.save_weights_only = save_weights_only

        # User-friendly warning when trying to save the best model.
        if self.save_best_only:
            self._check_filepath()

        self._is_old_tf_keras_version: Optional[bool] = None

    def on_train_batch_end(
        self, batch: int, logs: Optional[Dict[str, float]] = None
    ) -> None:
        if self._should_save_on_batch(batch):
            if self.is_old_tf_keras_version:
                # Save the model and get filepath
                self._save_model(epoch=self._current_epoch, logs=logs)
                filepath = self._get_file_path(epoch=self._current_epoch, logs=logs)
            else:
                # Save the model and get filepath
                self._save_model(epoch=self._current_epoch, batch=batch, logs=logs)
                filepath = self._get_file_path(
                    epoch=self._current_epoch, batch=batch, logs=logs
                )
            # Log the model as artifact
            aliases = ["latest", f"epoch_{self._current_epoch}_batch_{batch}"]
            self._log_ckpt_as_artifact(filepath, aliases=aliases)

    def on_epoch_end(self, epoch: int, logs: Optional[Dict[str, float]] = None) -> None:
        super().on_epoch_end(epoch, logs)
        # Check if model checkpoint is created at the end of epoch.
        if self.save_freq == "epoch":
            # Get filepath where the model checkpoint is saved.
            if self.is_old_tf_keras_version:
                filepath = self._get_file_path(epoch=epoch, logs=logs)
            else:
                filepath = self._get_file_path(epoch=epoch, batch=None, logs=logs)
            # Log the model as artifact
            aliases = ["latest", f"epoch_{epoch}"]
            self._log_ckpt_as_artifact(filepath, aliases=aliases)

    def _log_ckpt_as_artifact(
        self, filepath: str, aliases: Optional[List[str]] = None
    ) -> None:
        """Log model checkpoint as  W&B Artifact."""
        try:
            assert wandb.run is not None
            model_checkpoint_artifact = wandb.Artifact(
                f"run_{wandb.run.id}_model", type="model"
            )
            if os.path.isfile(filepath):
                model_checkpoint_artifact.add_file(filepath)
            elif os.path.isdir(filepath):
                model_checkpoint_artifact.add_dir(filepath)
            else:
                raise FileNotFoundError(f"No such file or directory {filepath}")
            wandb.log_artifact(model_checkpoint_artifact, aliases=aliases or [])
        except ValueError:
            # This error occurs when `save_best_only=True` and the model
            # checkpoint is not saved for that epoch/batch. Since TF/Keras
            # is giving friendly log, we can avoid clustering the stdout.
            pass

    def _check_filepath(self) -> None:
        placeholders = []
        for tup in string.Formatter().parse(self.filepath):
            if tup[1] is not None:
                placeholders.append(tup[1])
        if len(placeholders) == 0:
            wandb.termwarn(
                "When using `save_best_only`, ensure that the `filepath` argument "
                "contains formatting placeholders like `{epoch:02d}` or `{batch:02d}`. "
                "This ensures correct interpretation of the logged artifacts.",
                repeat=False,
            )

    @property
    def is_old_tf_keras_version(self) -> Optional[bool]:
        if self._is_old_tf_keras_version is None:
            from wandb.util import parse_version

            try:
                if parse_version(tf.keras.__version__) < parse_version("2.6.0"):
                    self._is_old_tf_keras_version = True
                else:
                    self._is_old_tf_keras_version = False
            except AttributeError:
                self._is_old_tf_keras_version = False

        return self._is_old_tf_keras_version
