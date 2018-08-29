import copy
import operator
import os
import numpy as np
import wandb
import sys
from importlib import import_module
from itertools import chain
try:
    import keras
    import keras.backend as K
except ImportError:
    import tensorflow.keras as keras
    import tensorflow.keras.backend as K


class WandbCallback(keras.callbacks.Callback):
    """WandB Keras Callback.

    Automatically saves history and summary data.  Optionally logs gradients, writes modes,
    and saves example images.

    Optionally saves the best model while training.

    Optionally logs weights and gradients during training.

    """

    def __init__(self, monitor='val_loss', verbose=0, mode='auto',
                 save_weights_only=False, log_weights=False, log_gradients=False,
                 save_model=True, training_data=None, validation_data=None,
                 labels=[], data_type=None, predictions=36, generator=None
                 ):
        """Constructor.

        # Arguments
            monitor: quantity to monitor.
            mode: one of {auto, min, max}.
                'min' - save model when monitor is minimized
                'max' - save model when monitor is maximized
                'auto' - try to guess when to save the model
            save_weights_only: if True, then only the model's weights will be
                saved (`model.save_weights(filepath)`), else the full model
                is saved (`model.save(filepath)`).
            save_model:
                True - save a model when monitor beats all previous epochs
                False - don't save models
            log_weights: if True save the weights in wandb.history
            log_gradients: if True log the training gradients in wandb.history
            training_data: tuple (X,y) needed for calculating gradients
            data_type: the type of data we're saving, set to "image" for saving images
            labels: list of labels to convert numeric output to if you are building a 
                multiclass classifier.  If you are making a binary classifier you can pass in
                a list of two labels ["label for false", "label for true"]
            predictions: the number of predictions to make each epic if data_type is set, max is 100.
            generator: a generator to use for making predictions
        """
        if wandb.run is None:
            raise wandb.Error(
                'You must call wandb.init() before WandbCallback()')
        if validation_data is not None:
            wandb.termlog(
                "DEPRECATED: validation_data is pulled from the model definition, set data_type.")
            # For backwards compatability
            self.data_type = data_type or "image"

        self.labels = labels
        self.data_type = data_type
        self.predictions = min(predictions, 100)

        self.monitor = monitor
        self.verbose = verbose
        self.save_weights_only = save_weights_only

        self.filepath = os.path.join(wandb.run.dir, 'model-best.h5')
        self.save_model = save_model
        self.log_weights = log_weights
        self.log_gradients = log_gradients
        self.training_data = training_data
        self.generator = generator

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

    def set_params(self, params):
        self.params = params

    def set_model(self, model):
        self.model = model
        wandb.run.summary['graph'] = wandb.Graph.from_keras(self.model)
        # Ensure summary is still auto-written
        wandb.run._user_accessed_summary = False

    def on_epoch_end(self, epoch, logs={}):
        if self.log_weights:
            wandb.log(self._log_weights(), commit=False)

        if self.log_gradients:
            wandb.log(self._log_gradients(), commit=False)

        if self.data_type == "image":
            if self.generator:
                self.validation_data = next(self.generator)
            if not hasattr(self, "validation_data"):
                wandb.termlog(
                    "WARNING: No validation_data set, if you're using a generator pass it to the callback.")
            elif self.validation_data and len(self.validation_data) > 0:
                wandb.log({"examples": self._log_images(
                    num_images=self.predictions)}, commit=False)

        wandb.log({'epoch': epoch}, commit=False)
        wandb.log(logs)

        self.current = logs.get(self.monitor)
        if self.current and self.monitor_op(self.current, self.best) and self.save_model:
            self._save_model(epoch)

    def on_batch_begin(self, batch, logs=None):
        pass

    def on_batch_end(self, batch, logs=None):
        pass

    def on_train_begin(self, logs=None):
        pass

    def on_train_end(self, logs=None):
        pass

    def _log_images(self, num_images=36):
        validation_X = self.validation_data[0]
        validation_y = self.validation_data[1]

        validation_length = len(validation_X)

        if validation_length > num_images:
            # pick some data at random
            indices = np.random.choice(validation_length, num_images)
        else:
            indices = range(validation_length)

        test_data = []
        test_output = []
        labels = []
        for i in indices:
            test_example = validation_X[i]
            test_data.append(test_example)
            test_output.append(validation_y[i])

        predictions = self.model.predict(np.stack(test_data))

        if (len(predictions[0].shape) == 1):
            if (predictions[0].shape[0] == 1):
                # Scalar output from the model
                # TODO: handle validation_y
                if len(self.labels) == 2:
                    # User has named true and false
                    captions = [self.labels[1] if prediction[0] >
                                0.5 else self.labels[0] for prediction in predictions]
                else:
                    if len(self.labels) != 0:
                        print(
                            "Warning: keras model is producing a single output, so labels should be a length two array: [\"False label\", \"True label\"].")
                    captions = [prediction[0] for prediction in predictions]

                return [wandb.Image(data, caption=str(captions[i])) for i, data in enumerate(test_data)]
            else:
                # Vector output from the model
                # TODO: handle validation_y
                labels = np.argmax(np.stack(predictions), axis=1)

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
                return [wandb.Image(data, caption=captions[i]) for i, data in enumerate(test_data)]
        elif (len(predictions[0].shape) == 2 or
              (len(predictions[0].shape) == 3 and predictions[0].shape[2] in [1, 3, 4])):
            # Looks like the model is outputting an image
            input_images = [wandb.Image(data, grouping=3)
                            for data in test_data]
            output_images = [wandb.Image(prediction)
                             for prediction in predictions]
            reference_images = [wandb.Image(data)
                                for data in test_output]
            return list(chain.from_iterable(zip(input_images, output_images, reference_images)))
        else:
            # More complicated output from the model, we'll just show the input
            return [wandb.Image(data) for data in test_data]

    def _log_weights(self):
        metrics = {}
        for layer in self.model.layers:
            weights = layer.get_weights()
            if len(weights) == 1:
                metrics[layer.name + ".weights"] = wandb.Histogram(weights[0])
            elif len(weights) == 2:
                metrics[layer.name + ".weights"] = wandb.Histogram(weights[0])
                metrics[layer.name + ".bias"] = wandb.Histogram(weights[1])
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
        input_tensors = [self.model.inputs[0],  # input data
                         # how much to weight each sample by
                         self.model.sample_weights[0],
                         self.model.targets[0],  # labels
                         K.learning_phase(),  # train or test mode
                         ]

        get_gradients = K.function(inputs=input_tensors, outputs=gradients)

        grads = get_gradients([X_train, np.ones(len(y_train)), y_train])

        for (weight, grad) in zip(weights, grads):
            metrics[weight.name.split(
                ':')[0] + ".gradient"] = wandb.Histogram(grad)

        return metrics

    def _save_model(self, epoch):
        if self.verbose > 0:
            print('Epoch %05d: %s improved from %0.5f to %0.5f,'
                  ' saving model to %s'
                  % (epoch, self.monitor, self.best,
                     self.current, self.filepath))
        self.best = self.current

        try:
            if self.save_weights_only:
                self.model.save_weights(self.filepath, overwrite=True)
            else:
                self.model.save(self.filepath, overwrite=True)
        except ImportError:
            print("Warning: Can't save model without h5py installed")
            self.save_model = False
