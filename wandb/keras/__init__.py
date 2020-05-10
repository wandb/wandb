import copy
import operator
import os
import numpy as np
import wandb
import sys
from importlib import import_module
from itertools import chain

# Use system keras if it's been imported
if "keras" in sys.modules:
    import keras
    import keras.backend as K
elif "tensorflow.python.keras" in sys.modules:
    import tensorflow.keras as keras
    import tensorflow.keras.backend as K
else:
    try:
        wandb.termwarn(
            "import wandb.keras called before import keras or import tensorflow.keras.  This can lead to a version mismatch, W&B now assumes tensorflow.keras")
        import tensorflow.keras as keras
        import tensorflow.keras.backend as K
    except ImportError:
        import keras
        import keras.backend as K


def is_dataset(data):
    dataset_ops = wandb.util.get_module(
        "tensorflow.python.data.ops.dataset_ops")
    if dataset_ops and hasattr(dataset_ops, "DatasetV2"):
        dataset_types = (dataset_ops.DatasetV2,)
        if hasattr(dataset_ops, "DatasetV1"):
            dataset_types = dataset_types + (dataset_ops.DatasetV1,)
        return isinstance(data, dataset_types)
    else:
        return False


def is_generator_like(data):
    # Checks if data is a generator, Sequence, or Iterator.

    types = (keras.utils.Sequence,)
    iterator_ops = wandb.util.get_module(
        "tensorflow.python.data.ops.iterator_ops")
    if iterator_ops:
        types = types + (iterator_ops.Iterator,)
        # EagerIterator was in tensorflow < 2
        if hasattr(iterator_ops, "EagerIterator"):
            types = types + (iterator_ops.EagerIterator,)
        elif hasattr(iterator_ops, "IteratorV2"):
            types = types + (iterator_ops.IteratorV2,)
    return (hasattr(data, 'next') or hasattr(data, '__next__') or isinstance(
        data, types))


def patch_tf_keras():
    import tensorflow as tf
    from tensorflow.python.eager import context
    from tensorflow.python.keras.engine import training
    from tensorflow.python.keras.engine import training_arrays
    from tensorflow.python.keras.engine import training_generator

    # Tensorflow 2.1
    training_v2_1 = wandb.util.get_module('tensorflow.python.keras.engine.training_v2')
    # Tensorflow 2.2
    training_v2_2 = wandb.util.get_module('tensorflow.python.keras.engine.training_v1')

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
                        "Found a validation dataset in graph mode, can't patch Keras.")
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
    wandb.patched["keras"].append(
        ["tensorflow.python.keras.engine.training_arrays", "fit_loop"])
    wandb.patched["keras"].append(
        ["tensorflow.python.keras.engine.training_generator", "fit_generator"])

    if training_v2_1:
        training_v2_1.Loop.fit = new_v2
        wandb.patched["keras"].append(
            ["tensorflow.python.keras.engine.training_v2.Loop", "fit"])
    elif training_v2_2:
        training.Model.fit = new_v2
        wandb.patched["keras"].append(
            ["tensorflow.python.keras.engine.training.Model", "fit"])

if "tensorflow" in wandb.util.get_full_typename(keras):
    try:
        patch_tf_keras()
    except Exception:
        wandb.termwarn(
            "Unable to patch tensorflow.keras for use with W&B.  You will not be able to log images unless you set the generator argument of the callback.")


class WandbCallback(keras.callbacks.Callback):
    """WandbCallback automatically integrates keras with wandb.

    Example:
        ```
        model.fit(X_train, y_train,  validation_data=(X_test, y_test),
            callbacks=[WandbCallback()])
        ```

    WandbCallback will automatically log history data from any
        metrics collected by keras: loss and anything passed into keras_model.compile() 

    WandbCallback will set summary metrics for the run associated with the "best" training
        step, where "best" is defined by the `monitor` and `mode` attribues.  This defaults
        to the epoch with the minimum val_loss. WandbCallback will by default save the model 
        associated with the best epoch..

    WandbCallback can optionally log gradient and parameter histograms. 

    WandbCallback can optionally save training and validation data for wandb to visualize.

    Args:
        monitor (str): name of metric to monitor.  Defaults to val_loss.
        mode (str): one of {"auto", "min", "max"}.
            "min" - save model when monitor is minimized
            "max" - save model when monitor is maximized
            "auto" - try to guess when to save the model (default).
        save_model:
            True - save a model when monitor beats all previous epochs
            False - don't save models
        save_weights_only (boolean): if True, then only the model's weights will be
            saved (`model.save_weights(filepath)`), else the full model
            is saved (`model.save(filepath)`).
        log_weights: (boolean) if True save histograms of the model's layer's weights.
        log_gradients: (boolean) if True log histograms of the training gradients
        training_data: (tuple) Same format (X,y) as passed to model.fit.  This is needed 
            for calculating gradients - this is mandatory if `log_gradients` is `True`.
        validate_data: (tuple) Same format (X,y) as passed to model.fit.  A set of data 
            for wandb to visualize.  If this is set, every epoch, wandb will
            make a small number of predictions and save the results for later visualization.
        generator (generator): a generator that returns validation data for wandb to visualize.  This
            generator should return tuples (X,y).  Either validate_data or generator should
            be set for wandb to visualize specific data examples.
        validation_steps (int): if `validation_data` is a generator, how many
            steps to run the generator for the full validation set.
        labels (list): If you are visualizing your data with wandb this list of labels 
            will convert numeric output to understandable string if you are building a
            multiclass classifier.  If you are making a binary classifier you can pass in
            a list of two labels ["label for false", "label for true"].  If validate_data
            and generator are both false, this won't do anything.
        predictions (int): the number of predictions to make for visualization each epoch, max 
            is 100.
        input_type (string): type of the model input to help visualization. can be one of:
            ("image", "images", "segmentation_mask").
        output_type (string): type of the model output to help visualziation. can be one of:
            ("image", "images", "segmentation_mask").  
        log_evaluation (boolean): if True save a dataframe containing the full
            validation results at the end of training.
        class_colors ([float, float, float]): if the input or output is a segmentation mask, 
            an array containing an rgb tuple (range 0-1) for each class.
        log_batch_frequency (integer): if None, callback will log every epoch.
            If set to integer, callback will log training metrics every log_batch_frequency 
            batches.
        log_best_prefix (string): if None, no extra summary metrics will be saved.
            If set to a string, the monitored metric and epoch will be prepended with this value
            and stored as summary metrics.
    """

    def __init__(self, monitor='val_loss', verbose=0, mode='auto',
                 save_weights_only=False, log_weights=False, log_gradients=False,
                 save_model=True, training_data=None, validation_data=None,
                 labels=[], data_type=None, predictions=36, generator=None,
                 input_type=None, output_type=None, log_evaluation=False,
                 validation_steps=None, class_colors=None, log_batch_frequency=None,
                 log_best_prefix="best_"):
        if wandb.run is None:
            raise wandb.Error(
                'You must call wandb.init() before WandbCallback()')

        self.validation_data = None
        # This is kept around for legacy reasons
        if validation_data is not None:
            if is_generator_like(validation_data):
                generator = validation_data
            else:
                self.validation_data = validation_data

        self.labels = labels
        self.predictions = min(predictions, 100)

        self.monitor = monitor
        self.verbose = verbose
        self.save_weights_only = save_weights_only

        wandb.save('model-best.h5')
        self.filepath = os.path.join(wandb.run.dir, 'model-best.h5')
        self.save_model = save_model
        self.log_weights = log_weights
        self.log_gradients = log_gradients
        self.training_data = training_data
        self.generator = generator
        self._graph_rendered = False

        self.input_type = input_type or data_type
        self.output_type = output_type
        self.log_evaluation = log_evaluation
        self.validation_steps = validation_steps
        self.class_colors = np.array(class_colors) if class_colors is not None else None
        self.log_batch_frequency = log_batch_frequency
        self.log_best_prefix = log_best_prefix

        if self.training_data:
            if len(self.training_data) != 2:
                raise ValueError("training data must be a tuple of length two")

        # From Keras
        if mode not in ['auto', 'min', 'max']:
            print('WandbCallback mode %s is unknown, '
                  'fallback to auto mode.' % (mode))
            mode = 'auto'

        if mode == 'min':
            self.monitor_op = operator.lt
            self.best = float('inf')
        elif mode == 'max':
            self.monitor_op = operator.gt
            self.best = float('-inf')
        else:
            if 'acc' in self.monitor or self.monitor.startswith('fmeasure'):
                self.monitor_op = operator.gt
                self.best = float('-inf')
            else:
                self.monitor_op = operator.lt
                self.best = float('inf')

    def _implements_train_batch_hooks(self):
        return self.log_batch_frequency is not None

    def _implements_test_batch_hooks(self):
        return self.log_batch_frequency is not None

    def _implements_predict_batch_hooks(self):
        return self.log_batch_frequency is not None

    def set_params(self, params):
        self.params = params

    def set_model(self, model):
        self.model = model
        if self.input_type == 'auto' and len(model.inputs) == 1:
            self.input_type = wandb.util.guess_data_type(model.inputs[0].shape, risky=True)
        if self.input_type and self.output_type is None and len(model.outputs) == 1:
            self.output_type = wandb.util.guess_data_type(model.outputs[0].shape)

    def on_epoch_end(self, epoch, logs={}):
        if self.log_weights:
            wandb.log(self._log_weights(), commit=False)

        if self.log_gradients:
            wandb.log(self._log_gradients(), commit=False)

        if self.input_type in ("image", "images", "segmentation_mask") or self.output_type in ("image", "images", "segmentation_mask"):
            if self.generator:
                self.validation_data = next(self.generator)
            if self.validation_data is None:
                wandb.termwarn(
                    "No validation_data set, pass a generator to the callback.")
            elif self.validation_data and len(self.validation_data) > 0:
                wandb.log({"examples": self._log_images(
                    num_images=self.predictions)}, commit=False)

        wandb.log({'epoch': epoch}, commit=False)
        wandb.log(logs, commit=True)

        self.current = logs.get(self.monitor)
        if self.current and self.monitor_op(self.current, self.best):
            if self.log_best_prefix:
                wandb.run.summary["%s%s" % (self.log_best_prefix, self.monitor)] = self.current
                wandb.run.summary["%s%s" % (self.log_best_prefix, "epoch")] = epoch
                if self.verbose and not self.save_model:
                    print('Epoch %05d: %s improved from %0.5f to %0.5f' % (
                        epoch, self.monitor, self.best, self.current))
            if self.save_model:
                self._save_model(epoch)
            self.best = self.current

    # This is what keras used pre tensorflow.keras
    def on_batch_begin(self, batch, logs=None):
        pass

    # This is what keras used pre tensorflow.keras
    def on_batch_end(self, batch, logs=None):
        if not self._graph_rendered:
            # Couldn't do this in train_begin because keras may still not be built
            wandb.run.summary['graph'] = wandb.Graph.from_keras(self.model)
            self._graph_rendered = True

        if self.log_batch_frequency and batch % self.log_batch_frequency == 0:
            wandb.log(logs, commit=True)

    def on_train_batch_begin(self, batch, logs=None):
        pass

    def on_train_batch_end(self, batch, logs=None):
        if not self._graph_rendered:
            # Couldn't do this in train_begin because keras may still not be built
            wandb.run.summary['graph'] = wandb.Graph.from_keras(self.model)
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
        pass

    def on_train_end(self, logs=None):
        if self.log_evaluation:
            wandb.run.summary['results'] = self._log_dataframe()
        pass

    def on_test_begin(self, logs=None):
        pass

    def on_test_end(self, logs=None):
        pass

    def on_test_batch_begin(self, batch, logs=None):
        pass

    def on_test_batch_end(self, batch, logs=None):
        pass

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
                captions = [self.labels[1] if logits[0] >
                            0.5 else self.labels[0] for logit in logits]
            else:
                if len(self.labels) != 0:
                    wandb.termwarn(
                        "keras model is producing a single output, so labels should be a length two array: [\"False label\", \"True label\"].")
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
        class_colors = self.class_colors if self.class_colors is not None else np.array(
            wandb.util.class_colors(masks[0].shape[2]))
        imgs = class_colors[np.argmax(masks, axis=-1)]
        return imgs

    def _log_images(self, num_images=36):
        validation_X = self.validation_data[0]
        validation_y = self.validation_data[1]

        validation_length = len(validation_X)

        if validation_length > num_images:
            # pick some data at random
            indices = np.random.choice(
                validation_length, num_images, replace=False)
        else:
            indices = range(validation_length)

        test_data = []
        test_output = []
        for i in indices:
            test_example = validation_X[i]
            test_data.append(test_example)
            test_output.append(validation_y[i])

        predictions = self.model.predict(np.stack(test_data))

        if self.input_type == 'label':
            if self.output_type in ('image', 'images', 'segmentation_mask'):
                captions = self._logits_to_captions(test_data)
                output_image_data = self._masks_to_pixels(
                    predictions) if self.output_type == 'segmentation_mask' else predictions
                reference_image_data = self._masks_to_pixels(
                    test_output) if self.output_type == 'segmentation_mask' else test_output
                output_images = [
                    wandb.Image(data, caption=captions[i], grouping=2)
                    for i, data in enumerate(output_image_data)
                ]
                reference_images = [
                    wandb.Image(data, caption=captions[i])
                    for i, data in enumerate(reference_image_data)
                ]
                return list(chain.from_iterable(zip(output_images, reference_images)))
        elif self.input_type in ('image', 'images', 'segmentation_mask'):
            input_image_data = self._masks_to_pixels(test_data) if self.input_type == 'segmentation_mask' else test_data
            if self.output_type == 'label':
                # we just use the predicted label as the caption for now
                captions = self._logits_to_captions(predictions)
                return [wandb.Image(data, caption=captions[i]) for i, data in enumerate(test_data)]
            elif self.output_type in ('image', 'images', 'segmentation_mask'):
                output_image_data = self._masks_to_pixels(
                    predictions) if self.output_type == 'segmentation_mask' else predictions
                reference_image_data = self._masks_to_pixels(
                    test_output) if self.output_type == 'segmentation_mask' else test_output
                input_images = [wandb.Image(data, grouping=3) for i, data in enumerate(input_image_data)]
                output_images = [wandb.Image(data) for i, data in enumerate(output_image_data)]
                reference_images = [wandb.Image(data) for i, data in enumerate(reference_image_data)]
                return list(chain.from_iterable(zip(input_images, output_images, reference_images)))
            else:
                # unknown output, just log the input images
                return [wandb.Image(img) for img in test_data]
        elif self.output_type in ('image', 'images', 'segmentation_mask'):
            # unknown input, just log the predicted and reference outputs without captions
            output_image_data = self._masks_to_pixels(
                predictions) if self.output_type == 'segmentation_mask' else predictions
            reference_image_data = self._masks_to_pixels(
                test_output) if self.output_type == 'segmentation_mask' else test_output
            output_images = [wandb.Image(data, grouping=2) for i, data in enumerate(output_image_data)]
            reference_images = [wandb.Image(data) for i, data in enumerate(reference_image_data)]
            return list(chain.from_iterable(zip(output_images, reference_images)))

    def _log_weights(self):
        metrics = {}
        for layer in self.model.layers:
            weights = layer.get_weights()
            if len(weights) == 1:
                metrics["parameters/" + layer.name +
                        ".weights"] = wandb.Histogram(weights[0])
            elif len(weights) == 2:
                metrics["parameters/" + layer.name +
                        ".weights"] = wandb.Histogram(weights[0])
                metrics["parameters/" + layer.name +
                        ".bias"] = wandb.Histogram(weights[1])
        return metrics

    def _log_gradients(self):
        if (not self.training_data):
            raise ValueError(
                "Need to pass in training data if logging gradients")

        X_train = self.training_data[0]
        y_train = self.training_data[1]
        metrics = {}
        weights = self.model.trainable_weights  # weight tensors
        # filter down weights tensors to only ones which are trainable
        weights = [weight for weight in weights
                   if self.model.get_layer(weight.name.split('/')[0]).trainable]

        gradients = self.model.optimizer.get_gradients(
            self.model.total_loss, weights)  # gradient tensors
        if hasattr(self.model, "targets"):
            # TF < 1.14
            target = self.model.targets[0]
            sample_weight = self.model.sample_weights[0]
        elif hasattr(self.model, "_training_endpoints") and len(self.model._training_endpoints) > 0:
            # TF > 1.14 TODO: not sure if we're handling sample_weight properly here...
            target = self.model._training_endpoints[0].training_target.target
            sample_weight = self.model._training_endpoints[0].sample_weight or K.variable(1)
        else:
            wandb.termwarn(
                "Couldn't extract gradients from your model, this could be an unsupported version of keras.  File an issue here: https://github.com/wandb/client", repeat=False)
            return metrics
        input_tensors = [self.model.inputs[0],  # input data
                         # how much to weight each sample by
                         sample_weight,
                         target,  # labels
                         K.learning_phase(),  # train or test mode
                         ]

        get_gradients = K.function(inputs=input_tensors, outputs=gradients)
        grads = get_gradients([X_train, np.ones(len(y_train)), y_train])

        for (weight, grad) in zip(weights, grads):
            metrics["gradients/" + weight.name.split(
                ':')[0] + ".gradient"] = wandb.Histogram(grad)

        return metrics

    def _log_dataframe(self):
        x, y_true, y_pred = None, None, None

        if self.validation_data:
            x, y_true = self.validation_data[0], self.validation_data[1]
            y_pred = self.model.predict(x)
        elif self.generator:
            if not self.validation_steps:
                wandb.termwarn(
                    'when using a generator for validation data with dataframes, you must pass validation_steps. skipping')
                return None

            for i in range(self.validation_steps):
                bx, by_true = next(self.generator)
                by_pred = self.model.predict(bx)
                if x is None:
                    x, y_true, y_pred = bx, by_true, by_pred
                else:
                    x, y_true, y_pred = np.append(x, bx, axis=0), np.append(
                        y_true, by_true, axis=0), np.append(y_pred, by_pred, axis=0)

        if self.input_type in ('image', 'images') and self.output_type == 'label':
            return wandb.image_categorizer_dataframe(x=x, y_true=y_true, y_pred=y_pred, labels=self.labels)
        elif self.input_type in ('image', 'images') and self.output_type == 'segmentation_mask':
            return wandb.image_segmentation_dataframe(x=x, y_true=y_true, y_pred=y_pred, labels=self.labels, class_colors=self.class_colors)
        else:
            wandb.termwarn('unknown dataframe type for input_type=%s and output_type=%s' %
                           (self.input_type, self.output_type))
            return None

    def _save_model(self, epoch):
        if self.verbose > 0:
            print('Epoch %05d: %s improved from %0.5f to %0.5f,'
                  ' saving model to %s'
                  % (epoch, self.monitor, self.best,
                     self.current, self.filepath))

        try:
            if self.save_weights_only:
                self.model.save_weights(self.filepath, overwrite=True)
            else:
                self.model.save(self.filepath, overwrite=True)
        # Was getting `RuntimeError: Unable to create link` in TF 1.13.1
        # also saw `TypeError: can't pickle _thread.RLock objects`
        except (ImportError, RuntimeError, TypeError) as e:
            wandb.termerror(
                "Can't save model, h5py returned error: %s" % e)
            self.save_model = False


__all__ = ['WandbCallback']
