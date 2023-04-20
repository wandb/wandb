import glob
import os
import string
import sys
from typing import Any, Dict, List, Optional, Union

import tensorflow as tf  # type: ignore
from tensorflow.keras import callbacks  # type: ignore

import wandb
from wandb.sdk.lib import telemetry

from ..keras import patch_tf_keras

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


Mode = Literal["auto", "min", "max"]
SaveStrategy = Literal["epoch"]

patch_tf_keras()


class WandbModelCheckpoint(callbacks.ModelCheckpoint):
    """A checkpoint that periodically saves a Keras model or model weights.

    Saves weights are uploaded to W&B as a `wandb.Artifact`.

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

    Arguments:
        filepath (Union[str, os.PathLike]): path to save the model file.
        monitor (str): The metric name to monitor.
        verbose (int): Verbosity mode, 0 or 1. Mode 0 is silent, and mode 1
            displays messages when the callback takes an action.
        save_best_only (bool): if `save_best_only=True`, it only saves when the model
            is considered the "best" and the latest best model according to the
            quantity monitored will not be overwritten.
        save_weights_only (bool): if True, then only the model's weights will be saved.
        mode (Mode): one of {'auto', 'min', 'max'}. For `val_acc`, this should be `max`,
            for `val_loss` this should be `min`, etc.
        save_freq (Union[SaveStrategy, int]): `epoch` or integer. When using `'epoch'`,
            the callback saves the model after each epoch. When using an integer, the
            callback saves the model at end of this many batches.
            Note that when monitoring validation metrics such as `val_acc` or `val_loss`,
            save_freq must be set to "epoch" as those metrics are only available at the
            end of an epoch.

        options (Optional[str]): Optional `tf.train.CheckpointOptions` object if
            `save_weights_only` is true or optional `tf.saved_model.SaveOptions`
            object if `save_weights_only` is false.
        initial_value_threshold (Optional[float]): Floating point initial "best" value of the metric
            to be monitored.
    """

    def __init__(
        self,
        filepath: Union[str, os.PathLike],
        monitor: str = "val_loss",
        verbose: int = 0,
        save_best_only: bool = False,
        save_weights_only: bool = False,
        mode: Mode = "auto",
        save_freq: Union[SaveStrategy, int] = "epoch",
        options: Optional[str] = None,
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
            options=options,
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
            model_artifact = wandb.Artifact(f"run_{wandb.run.id}_model", type="model")
            if self.save_weights_only:
                # We get three files when this is True
                model_artifact.add_file(
                    os.path.join(os.path.dirname(filepath), "checkpoint")
                )
                model_artifact.add_file(filepath + ".index")
                # In a distributed setting we get multiple shards.
                for file in glob.glob(f"{filepath}.data-*"):
                    model_artifact.add_file(file)
            elif filepath.endswith(".h5"):
                # Model saved in .h5 format thus we get one file.
                model_artifact.add_file(filepath)
            else:
                # Model saved in the SavedModel format thus we have dir.
                model_artifact.add_dir(filepath)
            wandb.log_artifact(model_artifact, aliases=aliases or [])
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
            from pkg_resources import parse_version

            if parse_version(tf.keras.__version__) < parse_version("2.6.0"):
                self._is_old_tf_keras_version = True
            else:
                self._is_old_tf_keras_version = False

        return self._is_old_tf_keras_version
