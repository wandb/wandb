import sys
from typing import Any, Dict, List, Tuple, Optional, Union

import numpy as np
import tensorflow as tf  # type: ignore
from tensorflow.keras import callbacks  # type: ignore

import wandb
from wandb.integration.keras.keras import (
    patch_tf_keras,
    _can_compute_flops,
    _CustomOptimizer,
    _GradAccumulatorCallback,
)

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


LogStrategy = Literal["epoch", "batch"]
Tensor = Union[Union[List[tf.Tensor], tf.Tensor], Union[List[np.array], np.array]]


tf_logger = tf.get_logger()
patch_tf_keras()


def count_params(weights) -> int:
    """Count the total number of scalars composing the weights.
    Reference:
        https://github.com/keras-team/keras/blob/e6784e4302c7b8cd116b74a784f4b78d60e83c26/keras/utils/layer_utils.py#L107
    Args:
        weights: An iterable containing the weights on which to compute params
    Returns:
        (int): The total number of scalars composing the weights
    """
    unique_weights = {id(w): w for w in weights}.values()
    # Ignore TrackableWeightHandlers, which will not have a shape defined.
    unique_weights = [w for w in unique_weights if hasattr(w, "shape")]
    weight_shapes = [w.shape.as_list() for w in unique_weights]
    standardized_weight_shapes = [
        [0 if w_i is None else w_i for w_i in w] for w in weight_shapes
    ]
    return int(sum(np.prod(p) for p in standardized_weight_shapes))


class WandbModelSurgeryCallback(callbacks.Callback):
    def __init__(
        self,
        input_specs: Optional[List[Any]] = None,
        train_data: Optional[Tuple[Tensor, Tensor]] = None,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.input_specs = input_specs
        self.train_data = train_data

    def _check_gradient_logging_possibility(self):
        if self.input_specs is None:
            self.input_specs = self.model.inputs
            return self.input_specs not in [None, []]
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
            self.train_data_x,
            self.train_data_y,
            verbose=0,
            callbacks=[self._grad_accumulator_callback],
        )
        tf_logger.setLevel(og_level)
        weights = self.model.trainable_weights
        grads = self._grad_accumulator_callback.grads
        metrics = {}
        for weight, grad in zip(weights, grads):
            metrics[
                "gradients/" + weight.name.split(":")[0].replace("/", "|") + ".gradient"
            ] = wandb.Histogram(grad)
        return metrics

    def _unpack_training_data(self):
        if self.train_data is not None:
            self.train_data_x, self.train_data_y = self.train_data
        else:
            input_shapes = [input_spec.shape for input_spec in self.input_specs]
            self.train_data_x = [
                tf.convert_to_tensor(np.random.rand(1, *shape[1:]))
                for shape in input_shapes
            ]
            self.train_data_x = (
                self.train_data_x[0]
                if len(self.train_data_x) == 1
                else self.train_data_x
            )
            self.train_data_y = self.model(self.train_data_x)

    def get_flops(self) -> float:
        """
        Calculate FLOPS [GFLOPs] for a tf.keras.Model or tf.keras.Sequential model
        in inference mode. It uses tf.compat.v1.profiler under the hood.
        """
        if not hasattr(self, "model"):
            raise wandb.Error("self.model must be set before using this method.")

        if not isinstance(
            self.model, (tf.keras.models.Sequential, tf.keras.models.Model)
        ):
            raise ValueError(
                "Calculating FLOPS is only supported for "
                "`tf.keras.Model` and `tf.keras.Sequential` instances."
            )

        from tensorflow.python.framework.convert_to_constants import (
            convert_variables_to_constants_v2_as_graph,
        )

        # convert tf.keras model into frozen graph to count FLOPs about operations used at inference
        real_model = tf.function(self.model).get_concrete_function(self.train_data_x)
        frozen_func, _ = convert_variables_to_constants_v2_as_graph(real_model)

        # Calculate FLOPs with tf.profiler
        run_meta = tf.compat.v1.RunMetadata()
        opts = (
            tf.compat.v1.profiler.ProfileOptionBuilder(
                tf.compat.v1.profiler.ProfileOptionBuilder().float_operation()
            )
            .with_empty_output()
            .build()
        )

        flops = tf.compat.v1.profiler.profile(
            graph=frozen_func.graph, run_meta=run_meta, cmd="scope", options=opts
        )

        # convert to GFLOPs
        return (flops.total_float_ops / 1e9) / 2

    def _count_params(self) -> Dict[str, float]:
        trainable_parameters = (
            count_params(self.model._collected_trainable_weights)
            if hasattr(self.model, "_collected_trainable_weights")
            else count_params(self.model.trainable_weights)
        )
        non_trainable_parameters = count_params(self.model.non_trainable_weights)
        return {
            "model/trainable-parameters": trainable_parameters,
            "model/non-trainable-parameters": non_trainable_parameters,
            "model/total-parameters": trainable_parameters + non_trainable_parameters,
        }

    def set_model(self, model):
        super().set_model(model)

        self.is_gradient_logging_possible = self._check_gradient_logging_possibility()

        if self.is_gradient_logging_possible:
            if not hasattr(self, "train_data_x"):
                self._unpack_training_data()
            self._build_grad_accumulator_model()

    def on_train_begin(self, logs=None):
        logs = dict() if logs is None else logs
        if _can_compute_flops() and self.is_gradient_logging_possible:
            if not hasattr(self, "train_data_x"):
                self._unpack_training_data()
            try:
                logs["model/GFLOPs"] = self.get_flops()
            except Exception as e:
                wandb.termwarn("Unable to compute FLOPs for this model.")
        logs = {**logs, **self._count_params()}
        wandb.log(logs, commit=False)

    def on_epoch_end(self, epoch: int, logs: Optional[Dict[str, Any]] = None) -> None:
        gradient_logs = self._get_gradient_logs()
        logs = {**logs, **gradient_logs}
        wandb.log(logs)
