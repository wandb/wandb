"""keras init."""

import logging
import operator
import os
import shutil
import sys
from itertools import chain

import numpy as np
import tensorflow as tf
import tensorflow.keras.backend as K  # noqa: N812

import wandb
from wandb.sdk.integration_utils.data_logging import ValidationDataLogger
from wandb.sdk.lib.deprecate import Deprecated, deprecate
from wandb.util import add_import_hook


def _check_keras_version():
    from keras import __version__ as keras_version

    from wandb.util import parse_version

    if parse_version(keras_version) < parse_version("2.4.0"):
        wandb.termwarn(
            f"Keras version {keras_version} is not fully supported. Required keras >= 2.4.0"
        )


def _can_compute_flops() -> bool:
    """FLOPS computation is restricted to TF 2.x as it requires tf.compat.v1."""
    from wandb.util import parse_version

    if parse_version(tf.__version__) >= parse_version("2.0.0"):
        return True

    return False


if "keras" in sys.modules:
    _check_keras_version()
else:
    add_import_hook("keras", _check_keras_version)


logger = logging.getLogger(__name__)


def is_dataset(data):
    dataset_ops = wandb.util.get_module("tensorflow.python.data.ops.dataset_ops")
    if dataset_ops and hasattr(dataset_ops, "DatasetV2"):
        dataset_types = (dataset_ops.DatasetV2,)
        if hasattr(dataset_ops, "DatasetV1"):
            dataset_types = dataset_types + (dataset_ops.DatasetV1,)
        return isinstance(data, dataset_types)
    else:
        return False


def is_generator_like(data):
    # Checks if data is a generator, Sequence, or Iterator.

    types = (tf.keras.utils.Sequence,)
    iterator_ops = wandb.util.get_module("tensorflow.python.data.ops.iterator_ops")
    if iterator_ops:
        types = types + (iterator_ops.Iterator,)
        # EagerIterator was in tensorflow < 2
        if hasattr(iterator_ops, "EagerIterator"):
            types = types + (iterator_ops.EagerIterator,)
        elif hasattr(iterator_ops, "IteratorV2"):
            types = types + (iterator_ops.IteratorV2,)
    return hasattr(data, "next") or hasattr(data, "__next__") or isinstance(data, types)


def patch_tf_keras():  # noqa: C901
    from tensorflow.python.eager import context

    from wandb.util import parse_version

    if (
        parse_version("2.6.0")
        <= parse_version(tf.__version__)
        < parse_version("2.13.0")
    ):
        keras_engine = "keras.engine"
        try:
            from keras.engine import training
            from keras.engine import training_arrays_v1 as training_arrays
            from keras.engine import training_generator_v1 as training_generator
        except (ImportError, AttributeError):
            wandb.termerror("Unable to patch Tensorflow/Keras")
            logger.exception("exception while trying to patch_tf_keras")
            return
    else:
        keras_engine = "tensorflow.python.keras.engine"

        from tensorflow.python.keras.engine import training

        try:
            from tensorflow.python.keras.engine import (
                training_arrays_v1 as training_arrays,
            )
            from tensorflow.python.keras.engine import (
                training_generator_v1 as training_generator,
            )
        except (ImportError, AttributeError):
            try:
                from tensorflow.python.keras.engine import (
                    training_arrays,
                    training_generator,
                )
            except (ImportError, AttributeError):
                wandb.termerror("Unable to patch Tensorflow/Keras")
                logger.exception("exception while trying to patch_tf_keras")
                return

    # Tensorflow 2.1
    training_v2_1 = wandb.util.get_module("tensorflow.python.keras.engine.training_v2")
    # Tensorflow 2.2
    training_v2_2 = wandb.util.get_module(f"{keras_engine}.training_v1")

    if training_v2_1:
        old_v2 = training_v2_1.Loop.fit
    elif training_v2_2:
        old_v2 = training.Model.fit

    old_arrays = training_arrays.fit_loop
    old_generator = training_generator.fit_generator

    def set_wandb_attrs(cbk, val_data):
        if isinstance(cbk, WandbCallback):
            if is_generator_like(val_data):
                cbk.generator = val_data
            elif is_dataset(val_data):
                if context.executing_eagerly():
                    cbk.generator = iter(val_data)
                else:
                    wandb.termwarn(
                        "Found a validation dataset in graph mode, can't patch Keras."
                    )
            elif isinstance(val_data, tuple) and isinstance(val_data[0], tf.Tensor):
                # Graph mode dataset generator
                def gen():
                    while True:
                        yield K.get_session().run(val_data)

                cbk.generator = gen()
            else:
                cbk.validation_data = val_data

    def new_arrays(*args, **kwargs):
        cbks = kwargs.get("callbacks", [])
        val_inputs = kwargs.get("val_inputs")
        val_targets = kwargs.get("val_targets")
        # TODO: these could be generators, why index 0?
        if val_inputs and val_targets:
            for cbk in cbks:
                set_wandb_attrs(cbk, (val_inputs[0], val_targets[0]))
        return old_arrays(*args, **kwargs)

    def new_generator(*args, **kwargs):
        cbks = kwargs.get("callbacks", [])
        val_data = kwargs.get("validation_data")
        if val_data:
            for cbk in cbks:
                set_wandb_attrs(cbk, val_data)
        return old_generator(*args, **kwargs)

    def new_v2(*args, **kwargs):
        cbks = kwargs.get("callbacks", [])
        val_data = kwargs.get("validation_data")
        if val_data:
            for cbk in cbks:
                set_wandb_attrs(cbk, val_data)
        return old_v2(*args, **kwargs)

    training_arrays.orig_fit_loop = old_arrays
    training_arrays.fit_loop = new_arrays
    training_generator.orig_fit_generator = old_generator
    training_generator.fit_generator = new_generator
    wandb.patched["keras"].append([f"{keras_engine}.training_arrays", "fit_loop"])
    wandb.patched["keras"].append(
        [f"{keras_engine}.training_generator", "fit_generator"]
    )

    if training_v2_1:
        training_v2_1.Loop.fit = new_v2
        wandb.patched["keras"].append(
            ["tensorflow.python.keras.engine.training_v2.Loop", "fit"]
        )
    elif training_v2_2:
        training.Model.fit = new_v2
        wandb.patched["keras"].append([f"{keras_engine}.training.Model", "fit"])


def _array_has_dtype(array):
    return hasattr(array, "dtype")


def _update_if_numeric(metrics, key, values):
    if not _array_has_dtype(values):
        _warn_not_logging(key)
        return

    if not is_numeric_array(values):
        _warn_not_logging_non_numeric(key)
        return

    metrics[key] = wandb.Histogram(values)


def is_numeric_array(array):
    return np.issubdtype(array.dtype, np.number)


def _warn_not_logging_non_numeric(name):
    wandb.termwarn(
        f"Non-numeric values found in layer: {name}, not logging this layer",
        repeat=False,
    )


def _warn_not_logging(name):
    wandb.termwarn(
        f"Layer {name} has undetermined datatype not logging this layer",
        repeat=False,
    )


tf_logger = tf.get_logger()

patch_tf_keras()


### For gradient logging ###


def _get_custom_optimizer_parent_class():
    from wandb.util import parse_version

    if parse_version(tf.__version__) >= parse_version("2.9.0"):
        custom_optimizer_parent_class = tf.keras.optimizers.legacy.Optimizer
    else:
        custom_optimizer_parent_class = tf.keras.optimizers.Optimizer

    return custom_optimizer_parent_class


_custom_optimizer_parent_class = _get_custom_optimizer_parent_class()


class _CustomOptimizer(_custom_optimizer_parent_class):
    def __init__(self):
        super().__init__(name="CustomOptimizer")
        self._resource_apply_dense = tf.function(self._resource_apply_dense)
        self._resource_apply_sparse = tf.function(self._resource_apply_sparse)

    def _resource_apply_dense(self, grad, var):
        var.assign(grad)

    # this needs to be implemented to prevent a NotImplementedError when
    # using Lookup layers.
    def _resource_apply_sparse(self, grad, var, indices):
        pass

    def get_config(self):
        return super().get_config()


class _GradAccumulatorCallback(tf.keras.callbacks.Callback):
    """Accumulates gradients during a fit() call when used in conjunction with the CustomOptimizer above."""

    def set_model(self, model):
        super().set_model(model)
        self.og_weights = model.get_weights()
        self.grads = [np.zeros(tuple(w.shape)) for w in model.trainable_weights]

    def on_batch_end(self, batch, logs=None):
        for g, w in zip(self.grads, self.model.trainable_weights):
            g += w.numpy()
        self.model.set_weights(self.og_weights)

    def get_grads(self):
        return [g.copy() for g in self.grads]


###


class WandbCallback(tf.keras.callbacks.Callback):
    """`WandbCallback` automatically integrates keras with wandb.

    Example:
        ```python
        model.fit(
            X_train,
            y_train,
            validation_data=(X_test, y_test),
            callbacks=[WandbCallback()],
        )
        ```

    `WandbCallback` will automatically log history data from any
    metrics collected by keras: loss and anything passed into `keras_model.compile()`.

    `WandbCallback` will set summary metrics for the run associated with the "best" training
    step, where "best" is defined by the `monitor` and `mode` attributes.  This defaults
    to the epoch with the minimum `val_loss`. `WandbCallback` will by default save the model
    associated with the best `epoch`.

    `WandbCallback` can optionally log gradient and parameter histograms.

    `WandbCallback` can optionally save training and validation data for wandb to visualize.

    Arguments:
        monitor: (str) name of metric to monitor.  Defaults to `val_loss`.
        mode: (str) one of {`auto`, `min`, `max`}.
            `min` - save model when monitor is minimized
            `max` - save model when monitor is maximized
            `auto` - try to guess when to save the model (default).
        save_model:
            True - save a model when monitor beats all previous epochs
            False - don't save models
        save_graph: (boolean) if True save model graph to wandb (default to True).
        save_weights_only: (boolean) if True, then only the model's weights will be
            saved (`model.save_weights(filepath)`), else the full model
            is saved (`model.save(filepath)`).
        log_weights: (boolean) if True save histograms of the model's layer's weights.
        log_gradients: (boolean) if True log histograms of the training gradients
        training_data: (tuple) Same format `(X,y)` as passed to `model.fit`.  This is needed
            for calculating gradients - this is mandatory if `log_gradients` is `True`.
        validation_data: (tuple) Same format `(X,y)` as passed to `model.fit`.  A set of data
            for wandb to visualize.  If this is set, every epoch, wandb will
            make a small number of predictions and save the results for later visualization. In case
            you are working with image data, please also set `input_type` and `output_type` in order
            to log correctly.
        generator: (generator) a generator that returns validation data for wandb to visualize.  This
            generator should return tuples `(X,y)`.  Either `validate_data` or generator should
            be set for wandb to visualize specific data examples. In case you are working with image data,
            please also set `input_type` and `output_type` in order to log correctly.
        validation_steps: (int) if `validation_data` is a generator, how many
            steps to run the generator for the full validation set.
        labels: (list) If you are visualizing your data with wandb this list of labels
            will convert numeric output to understandable string if you are building a
            multiclass classifier.  If you are making a binary classifier you can pass in
            a list of two labels ["label for false", "label for true"].  If `validate_data`
            and generator are both false, this won't do anything.
        predictions: (int) the number of predictions to make for visualization each epoch, max
            is 100.
        input_type: (string) type of the model input to help visualization. can be one of:
            (`image`, `images`, `segmentation_mask`, `auto`).
        output_type: (string) type of the model output to help visualization. can be one of:
            (`image`, `images`, `segmentation_mask`, `label`).
        log_evaluation: (boolean) if True, save a Table containing validation data and the
            model's predictions at each epoch. See `validation_indexes`,
            `validation_row_processor`, and `output_row_processor` for additional details.
        class_colors: ([float, float, float]) if the input or output is a segmentation mask,
            an array containing an rgb tuple (range 0-1) for each class.
        log_batch_frequency: (integer) if None, callback will log every epoch.
            If set to integer, callback will log training metrics every `log_batch_frequency`
            batches.
        log_best_prefix: (string) if None, no extra summary metrics will be saved.
            If set to a string, the monitored metric and epoch will be prepended with this value
            and stored as summary metrics.
        validation_indexes: ([wandb.data_types._TableLinkMixin]) an ordered list of index keys to associate
            with each validation example.  If log_evaluation is True and `validation_indexes` is provided,
            then a Table of validation data will not be created and instead each prediction will
            be associated with the row represented by the `TableLinkMixin`. The most common way to obtain
            such keys are is use `Table.get_index()` which will return a list of row keys.
        validation_row_processor: (Callable) a function to apply to the validation data, commonly used to visualize the data.
            The function will receive an `ndx` (int) and a `row` (dict). If your model has a single input,
            then `row["input"]` will be the input data for the row. Else, it will be keyed based on the name of the
            input slot. If your fit function takes a single target, then `row["target"]` will be the target data for the row. Else,
            it will be keyed based on the name of the output slots. For example, if your input data is a single ndarray,
            but you wish to visualize the data as an Image, then you can provide `lambda ndx, row: {"img": wandb.Image(row["input"])}`
            as the processor. Ignored if log_evaluation is False or `validation_indexes` are present.
        output_row_processor: (Callable) same as `validation_row_processor`, but applied to the model's output. `row["output"]` will contain
            the results of the model output.
        infer_missing_processors: (bool) Determines if `validation_row_processor` and `output_row_processor`
            should be inferred if missing. Defaults to True. If `labels` are provided, we will attempt to infer classification-type
            processors where appropriate.
        log_evaluation_frequency: (int) Determines the frequency which evaluation results will be logged. Default 0 (only at the end of training).
            Set to 1 to log every epoch, 2 to log every other epoch, and so on. Has no effect when log_evaluation is False.
        compute_flops: (bool) Compute the FLOPs of your Keras Sequential or Functional model in GigaFLOPs unit.
    """

    def __init__(
        self,
        monitor="val_loss",
        verbose=0,
        mode="auto",
        save_weights_only=False,
        log_weights=False,
        log_gradients=False,
        save_model=True,
        training_data=None,
        validation_data=None,
        labels=None,
        predictions=36,
        generator=None,
        input_type=None,
        output_type=None,
        log_evaluation=False,
        validation_steps=None,
        class_colors=None,
        log_batch_frequency=None,
        log_best_prefix="best_",
        save_graph=True,
        validation_indexes=None,
        validation_row_processor=None,
        prediction_row_processor=None,
        infer_missing_processors=True,
        log_evaluation_frequency=0,
        compute_flops=False,
        **kwargs,
    ):
        if wandb.run is None:
            raise wandb.Error("You must call wandb.init() before WandbCallback()")

        deprecate(
            field_name=Deprecated.keras_callback,
            warning_message=(
                "WandbCallback is deprecated and will be removed in a future release. "
                "Please use the WandbMetricsLogger, WandbModelCheckpoint, and WandbEvalCallback "
                "callbacks instead. "
                "See https://docs.wandb.ai/guides/integrations/keras for more information."
            ),
        )

        with wandb.wandb_lib.telemetry.context(run=wandb.run) as tel:
            tel.feature.keras = True
        self.validation_data = None
        # This is kept around for legacy reasons
        if validation_data is not None:
            if is_generator_like(validation_data):
                generator = validation_data
            else:
                self.validation_data = validation_data
        if labels is None:
            labels = []
        self.labels = labels
        self.predictions = min(predictions, 100)

        self.monitor = monitor
        self.verbose = verbose
        self.save_weights_only = save_weights_only
        self.save_graph = save_graph

        wandb.save("model-best.h5")
        self.filepath = os.path.join(wandb.run.dir, "model-best.h5")
        self.save_model = save_model
        if save_model:
            deprecate(
                field_name=Deprecated.keras_callback__save_model,
                warning_message=(
                    "The save_model argument by default saves the model in the HDF5 format that cannot save "
                    "custom objects like subclassed models and custom layers. This behavior will be deprecated "
                    "in a future release in favor of the SavedModel format. Meanwhile, the HDF5 model is saved "
                    "as W&B files and the SavedModel as W&B Artifacts."
                ),
            )

        self.save_model_as_artifact = True
        self.log_weights = log_weights
        self.log_gradients = log_gradients
        self.training_data = training_data
        self.generator = generator
        self._graph_rendered = False

        data_type = kwargs.get("data_type", None)
        if data_type is not None:
            deprecate(
                field_name=Deprecated.keras_callback__data_type,
                warning_message=(
                    "The data_type argument of wandb.keras.WandbCallback is deprecated "
                    "and will be removed in a future release. Please use input_type instead.\n"
                    "Setting input_type = data_type."
                ),
            )
            input_type = data_type
        self.input_type = input_type
        self.output_type = output_type
        self.log_evaluation = log_evaluation
        self.validation_steps = validation_steps
        self.class_colors = np.array(class_colors) if class_colors is not None else None
        self.log_batch_frequency = log_batch_frequency
        self.log_best_prefix = log_best_prefix
        self.compute_flops = compute_flops

        self._prediction_batch_size = None

        if self.log_gradients:
            if int(tf.__version__.split(".")[0]) < 2:
                raise Exception("Gradient logging requires tensorflow 2.0 or higher.")
            if self.training_data is None:
                raise ValueError(
                    "training_data argument is required for gradient logging."
                )
            if isinstance(self.training_data, (list, tuple)):
                if len(self.training_data) != 2:
                    raise ValueError("training data must be a tuple of length two")
                self._training_data_x, self._training_data_y = self.training_data
            else:
                self._training_data_x = (
                    self.training_data
                )  # generator, tf.data.Dataset etc
                self._training_data_y = None

        # From Keras
        if mode not in ["auto", "min", "max"]:
            print(f"WandbCallback mode {mode} is unknown, fallback to auto mode.")
            mode = "auto"

        if mode == "min":
            self.monitor_op = operator.lt
            self.best = float("inf")
        elif mode == "max":
            self.monitor_op = operator.gt
            self.best = float("-inf")
        else:
            if "acc" in self.monitor or self.monitor.startswith("fmeasure"):
                self.monitor_op = operator.gt
                self.best = float("-inf")
            else:
                self.monitor_op = operator.lt
                self.best = float("inf")
        # Get the previous best metric for resumed runs
        previous_best = wandb.run.summary.get(f"{self.log_best_prefix}{self.monitor}")
        if previous_best is not None:
            self.best = previous_best

        self._validation_data_logger = None
        self._validation_indexes = validation_indexes
        self._validation_row_processor = validation_row_processor
        self._prediction_row_processor = prediction_row_processor
        self._infer_missing_processors = infer_missing_processors
        self._log_evaluation_frequency = log_evaluation_frequency
        self._model_trained_since_last_eval = False

    def _build_grad_accumulator_model(self):
        inputs = self.model.inputs
        outputs = self.model(inputs)
        grad_acc_model = tf.keras.models.Model(inputs, outputs)
        grad_acc_model.compile(loss=self.model.loss, optimizer=_CustomOptimizer())

        # make sure magic doesn't think this is a user model
        grad_acc_model._wandb_internal_model = True

        self._grad_accumulator_model = grad_acc_model
        self._grad_accumulator_callback = _GradAccumulatorCallback()

    def _implements_train_batch_hooks(self):
        return self.log_batch_frequency is not None

    def _implements_test_batch_hooks(self):
        return self.log_batch_frequency is not None

    def _implements_predict_batch_hooks(self):
        return self.log_batch_frequency is not None

    def set_params(self, params):
        self.params = params

    def set_model(self, model):
        super().set_model(model)
        if self.input_type == "auto" and len(model.inputs) == 1:
            self.input_type = wandb.util.guess_data_type(
                model.inputs[0].shape, risky=True
            )
        if self.input_type and self.output_type is None and len(model.outputs) == 1:
            self.output_type = wandb.util.guess_data_type(model.outputs[0].shape)
        if self.log_gradients:
            self._build_grad_accumulator_model()

    def _attempt_evaluation_log(self, commit=True):
        if self.log_evaluation and self._validation_data_logger:
            try:
                if not self.model:
                    wandb.termwarn("WandbCallback unable to read model from trainer")
                else:
                    self._validation_data_logger.log_predictions(
                        predictions=self._validation_data_logger.make_predictions(
                            self.model.predict
                        ),
                        commit=commit,
                    )
                    self._model_trained_since_last_eval = False
            except Exception as e:
                wandb.termwarn("Error during prediction logging for epoch: " + str(e))

    def on_epoch_end(self, epoch, logs=None):
        if logs is None:
            logs = {}
        if self.log_weights:
            wandb.log(self._log_weights(), commit=False)

        if self.log_gradients:
            wandb.log(self._log_gradients(), commit=False)

        if self.input_type in (
            "image",
            "images",
            "segmentation_mask",
        ) or self.output_type in ("image", "images", "segmentation_mask"):
            if self.generator:
                self.validation_data = next(self.generator)
            if self.validation_data is None:
                wandb.termwarn(
                    "No validation_data set, pass a generator to the callback."
                )
            elif self.validation_data and len(self.validation_data) > 0:
                wandb.log(
                    {"examples": self._log_images(num_images=self.predictions)},
                    commit=False,
                )

        if (
            self._log_evaluation_frequency > 0
            and epoch % self._log_evaluation_frequency == 0
        ):
            self._attempt_evaluation_log(commit=False)

        wandb.log({"epoch": epoch}, commit=False)
        wandb.log(logs, commit=True)

        self.current = logs.get(self.monitor)
        if self.current and self.monitor_op(self.current, self.best):
            if self.log_best_prefix:
                wandb.run.summary[f"{self.log_best_prefix}{self.monitor}"] = (
                    self.current
                )
                wandb.run.summary["{}{}".format(self.log_best_prefix, "epoch")] = epoch
                if self.verbose and not self.save_model:
                    print(
                        "Epoch %05d: %s improved from %0.5f to %0.5f"
                        % (epoch, self.monitor, self.best, self.current)
                    )
            if self.save_model:
                self._save_model(epoch)

            if self.save_model and self.save_model_as_artifact:
                self._save_model_as_artifact(epoch)

            self.best = self.current

    # This is what keras used pre tensorflow.keras
    def on_batch_begin(self, batch, logs=None):
        pass

    # This is what keras used pre tensorflow.keras
    def on_batch_end(self, batch, logs=None):
        if self.save_graph and not self._graph_rendered:
            # Couldn't do this in train_begin because keras may still not be built
            wandb.run.summary["graph"] = wandb.Graph.from_keras(self.model)
            self._graph_rendered = True

        if self.log_batch_frequency and batch % self.log_batch_frequency == 0:
            wandb.log(logs, commit=True)

    def on_train_batch_begin(self, batch, logs=None):
        self._model_trained_since_last_eval = True

    def on_train_batch_end(self, batch, logs=None):
        if self.save_graph and not self._graph_rendered:
            # Couldn't do this in train_begin because keras may still not be built
            wandb.run.summary["graph"] = wandb.Graph.from_keras(self.model)
            self._graph_rendered = True

        if self.log_batch_frequency and batch % self.log_batch_frequency == 0:
            wandb.log(logs, commit=True)

    def on_test_begin(self, logs=None):
        pass

    def on_test_end(self, logs=None):
        pass

    def on_test_batch_begin(self, batch, logs=None):
        pass

    def on_test_batch_end(self, batch, logs=None):
        pass

    def on_train_begin(self, logs=None):
        if self.log_evaluation:
            try:
                validation_data = None
                if self.validation_data:
                    validation_data = self.validation_data
                elif self.generator:
                    if not self.validation_steps:
                        wandb.termwarn(
                            "WandbCallback is unable to log validation data. "
                            "When using a generator for validation_data, you must pass validation_steps"
                        )
                    else:
                        x = None
                        y_true = None
                        for _ in range(self.validation_steps):
                            bx, by_true = next(self.generator)
                            if x is None:
                                x, y_true = bx, by_true
                            else:
                                x, y_true = (
                                    np.append(x, bx, axis=0),
                                    np.append(y_true, by_true, axis=0),
                                )
                        validation_data = (x, y_true)
                else:
                    wandb.termwarn(
                        "WandbCallback is unable to read validation_data from trainer "
                        "and therefore cannot log validation data. Ensure Keras is properly "
                        "patched by calling `from wandb.keras import WandbCallback` at the top of your script."
                    )
                if validation_data:
                    self._validation_data_logger = ValidationDataLogger(
                        inputs=validation_data[0],
                        targets=validation_data[1],
                        indexes=self._validation_indexes,
                        validation_row_processor=self._validation_row_processor,
                        prediction_row_processor=self._prediction_row_processor,
                        class_labels=self.labels,
                        infer_missing_processors=self._infer_missing_processors,
                    )
            except Exception as e:
                wandb.termwarn(
                    "Error initializing ValidationDataLogger in WandbCallback. "
                    f"Skipping logging validation data. Error: {str(e)}"
                )

        if self.compute_flops and _can_compute_flops():
            try:
                wandb.summary["GFLOPs"] = self.get_flops()
            except Exception as e:
                wandb.termwarn("Unable to compute FLOPs for this model.")
                logger.exception(e)

    def on_train_end(self, logs=None):
        if self._model_trained_since_last_eval:
            self._attempt_evaluation_log()

    def on_predict_begin(self, logs=None):
        pass

    def on_predict_end(self, logs=None):
        pass

    def on_predict_batch_begin(self, batch, logs=None):
        pass

    def on_predict_batch_end(self, batch, logs=None):
        pass

    def _logits_to_captions(self, logits):
        if logits[0].shape[-1] == 1:
            # Scalar output from the model
            # TODO: handle validation_y
            if len(self.labels) == 2:
                # User has named true and false
                captions = [
                    self.labels[1] if logits[0] > 0.5 else self.labels[0]
                    for logit in logits
                ]
            else:
                if len(self.labels) != 0:
                    wandb.termwarn(
                        "keras model is producing a single output, "
                        'so labels should be a length two array: ["False label", "True label"].'
                    )
                captions = [logit[0] for logit in logits]
        else:
            # Vector output from the model
            # TODO: handle validation_y
            labels = np.argmax(np.stack(logits), axis=1)

            if len(self.labels) > 0:
                # User has named the categories in self.labels
                captions = []
                for label in labels:
                    try:
                        captions.append(self.labels[label])
                    except IndexError:
                        captions.append(label)
            else:
                captions = labels
        return captions

    def _masks_to_pixels(self, masks):
        # if its a binary mask, just return it as grayscale instead of picking the argmax
        if len(masks[0].shape) == 2 or masks[0].shape[-1] == 1:
            return masks
        class_colors = (
            self.class_colors
            if self.class_colors is not None
            else np.array(wandb.util.class_colors(masks[0].shape[2]))
        )
        imgs = class_colors[np.argmax(masks, axis=-1)]
        return imgs

    def _log_images(self, num_images=36):
        validation_X = self.validation_data[0]  # noqa: N806
        validation_y = self.validation_data[1]

        validation_length = len(validation_X)

        if validation_length > num_images:
            # pick some data at random
            indices = np.random.choice(validation_length, num_images, replace=False)
        else:
            indices = range(validation_length)

        test_data = []
        test_output = []
        for i in indices:
            test_example = validation_X[i]
            test_data.append(test_example)
            test_output.append(validation_y[i])

        if self.model.stateful:
            predictions = self.model.predict(np.stack(test_data), batch_size=1)
            self.model.reset_states()
        else:
            predictions = self.model.predict(
                np.stack(test_data), batch_size=self._prediction_batch_size
            )
            if len(predictions) != len(test_data):
                self._prediction_batch_size = 1
                predictions = self.model.predict(
                    np.stack(test_data), batch_size=self._prediction_batch_size
                )

        if self.input_type == "label":
            if self.output_type in ("image", "images", "segmentation_mask"):
                captions = self._logits_to_captions(test_data)
                output_image_data = (
                    self._masks_to_pixels(predictions)
                    if self.output_type == "segmentation_mask"
                    else predictions
                )
                reference_image_data = (
                    self._masks_to_pixels(test_output)
                    if self.output_type == "segmentation_mask"
                    else test_output
                )
                output_images = [
                    wandb.Image(data, caption=captions[i], grouping=2)
                    for i, data in enumerate(output_image_data)
                ]
                reference_images = [
                    wandb.Image(data, caption=captions[i])
                    for i, data in enumerate(reference_image_data)
                ]
                return list(chain.from_iterable(zip(output_images, reference_images)))
        elif self.input_type in ("image", "images", "segmentation_mask"):
            input_image_data = (
                self._masks_to_pixels(test_data)
                if self.input_type == "segmentation_mask"
                else test_data
            )
            if self.output_type == "label":
                # we just use the predicted label as the caption for now
                captions = self._logits_to_captions(predictions)
                return [
                    wandb.Image(data, caption=captions[i])
                    for i, data in enumerate(test_data)
                ]
            elif self.output_type in ("image", "images", "segmentation_mask"):
                output_image_data = (
                    self._masks_to_pixels(predictions)
                    if self.output_type == "segmentation_mask"
                    else predictions
                )
                reference_image_data = (
                    self._masks_to_pixels(test_output)
                    if self.output_type == "segmentation_mask"
                    else test_output
                )
                input_images = [
                    wandb.Image(data, grouping=3)
                    for i, data in enumerate(input_image_data)
                ]
                output_images = [
                    wandb.Image(data) for i, data in enumerate(output_image_data)
                ]
                reference_images = [
                    wandb.Image(data) for i, data in enumerate(reference_image_data)
                ]
                return list(
                    chain.from_iterable(
                        zip(input_images, output_images, reference_images)
                    )
                )
            else:
                # unknown output, just log the input images
                return [wandb.Image(img) for img in test_data]
        elif self.output_type in ("image", "images", "segmentation_mask"):
            # unknown input, just log the predicted and reference outputs without captions
            output_image_data = (
                self._masks_to_pixels(predictions)
                if self.output_type == "segmentation_mask"
                else predictions
            )
            reference_image_data = (
                self._masks_to_pixels(test_output)
                if self.output_type == "segmentation_mask"
                else test_output
            )
            output_images = [
                wandb.Image(data, grouping=2)
                for i, data in enumerate(output_image_data)
            ]
            reference_images = [
                wandb.Image(data) for i, data in enumerate(reference_image_data)
            ]
            return list(chain.from_iterable(zip(output_images, reference_images)))

    def _log_weights(self):
        metrics = {}
        for layer in self.model.layers:
            weights = layer.get_weights()
            if len(weights) == 1:
                _update_if_numeric(
                    metrics, "parameters/" + layer.name + ".weights", weights[0]
                )
            elif len(weights) == 2:
                _update_if_numeric(
                    metrics, "parameters/" + layer.name + ".weights", weights[0]
                )
                _update_if_numeric(
                    metrics, "parameters/" + layer.name + ".bias", weights[1]
                )
        return metrics

    def _log_gradients(self):
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
            metrics["gradients/" + weight.name.split(":")[0] + ".gradient"] = (
                wandb.Histogram(grad)
            )
        return metrics

    def _log_dataframe(self):
        x, y_true, y_pred = None, None, None

        if self.validation_data:
            x, y_true = self.validation_data[0], self.validation_data[1]
            y_pred = self.model.predict(x)
        elif self.generator:
            if not self.validation_steps:
                wandb.termwarn(
                    "when using a generator for validation data with dataframes, "
                    "you must pass validation_steps. skipping"
                )
                return None

            for _ in range(self.validation_steps):
                bx, by_true = next(self.generator)
                by_pred = self.model.predict(bx)
                if x is None:
                    x, y_true, y_pred = bx, by_true, by_pred
                else:
                    x, y_true, y_pred = (
                        np.append(x, bx, axis=0),
                        np.append(y_true, by_true, axis=0),
                        np.append(y_pred, by_pred, axis=0),
                    )

        if self.input_type in ("image", "images") and self.output_type == "label":
            return wandb.image_categorizer_dataframe(
                x=x, y_true=y_true, y_pred=y_pred, labels=self.labels
            )
        elif (
            self.input_type in ("image", "images")
            and self.output_type == "segmentation_mask"
        ):
            return wandb.image_segmentation_dataframe(
                x=x,
                y_true=y_true,
                y_pred=y_pred,
                labels=self.labels,
                class_colors=self.class_colors,
            )
        else:
            wandb.termwarn(
                f"unknown dataframe type for input_type={self.input_type} and output_type={self.output_type}"
            )
            return None

    def _save_model(self, epoch):
        if wandb.run.disabled:
            return
        if self.verbose > 0:
            print(
                "Epoch %05d: %s improved from %0.5f to %0.5f,"
                " saving model to %s"
                % (epoch, self.monitor, self.best, self.current, self.filepath)
            )

        try:
            if self.save_weights_only:
                self.model.save_weights(self.filepath, overwrite=True)
            else:
                self.model.save(self.filepath, overwrite=True)
        # Was getting `RuntimeError: Unable to create link` in TF 1.13.1
        # also saw `TypeError: can't pickle _thread.RLock objects`
        except (ImportError, RuntimeError, TypeError, AttributeError) as e:
            wandb.termerror(
                "Can't save model in the h5py format. The model will be saved as "
                "as an W&B Artifact in the 'tf' format."
            )
            logger.exception(e)

    def _save_model_as_artifact(self, epoch):
        if wandb.run.disabled:
            return

        # Save the model in the SavedModel format.
        # TODO: Replace this manual artifact creation with the `log_model` method
        # after `log_model` is released from beta.
        self.model.save(self.filepath[:-3], overwrite=True, save_format="tf")

        # Log the model as artifact.
        name = wandb.util.make_artifact_name_safe(f"model-{wandb.run.name}")
        model_artifact = wandb.Artifact(name, type="model")
        model_artifact.add_dir(self.filepath[:-3])
        wandb.run.log_artifact(model_artifact, aliases=["latest", f"epoch_{epoch}"])

        # Remove the SavedModel from wandb dir as we don't want to log it to save memory.
        shutil.rmtree(self.filepath[:-3])

    def get_flops(self) -> float:
        """Calculate FLOPS [GFLOPs] for a tf.keras.Model or tf.keras.Sequential model in inference mode.

        It uses tf.compat.v1.profiler under the hood.
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

        # Compute FLOPs for one sample
        batch_size = 1
        inputs = [
            tf.TensorSpec([batch_size] + inp.shape[1:], inp.dtype)
            for inp in self.model.inputs
        ]

        # convert tf.keras model into frozen graph to count FLOPs about operations used at inference
        real_model = tf.function(self.model).get_concrete_function(inputs)
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
