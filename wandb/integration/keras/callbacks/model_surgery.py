import sys
from typing import Any, Dict, List, Optional

import tensorflow as tf  # type: ignore
from tensorflow.keras import callbacks  # type: ignore

import wandb
from wandb.integration.keras.keras import (
    patch_tf_keras,
    _CustomOptimizer,
    _GradAccumulatorCallback,
)

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


LogStrategy = Literal["epoch", "batch"]


tf_logger = tf.get_logger()
patch_tf_keras()


class WandbModelSurgeryCallback(callbacks.Callback):
    def __init__(self, input_specs: Optional[List[Any]] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.input_specs = input_specs
        self.is_gradient_logging_possible = (
            self.is_flops_computation_possible
        ) = self._check_gradient_logging_possibility()

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
        gradient_logs = self._get_gradient_logs()
        logs = dict(logs.items() + gradient_logs.items())
        wandb.log(logs)
