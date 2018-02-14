import copy
import operator
import os
import numpy as np
import wandb
import sys
from importlib import import_module
import keras
import keras.backend as K


class WandbKerasCallback(keras.callbacks.Callback):
    """WandB Keras Callback.

    Automatically saves wandb-history.csv and wandb-summary.csv, both tracking
    keras metrics.

    Optionally saves the best model while training.

    Optionally logs weights and gradients during training.

    """

    def __init__(self, monitor='val_loss', verbose=0, mode='auto',
                 save_weights_only=False, log_weights=False, log_gradients=False,
                 save_model=True, training_data=None
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


        """
        if wandb.run is None:
            raise wandb.Error(
                'You must call wandb.init() before WandbKerasCallback()')
        self.validation_data = None

        self.monitor = monitor
        self.verbose = verbose
        self.save_weights_only = save_weights_only

        self.filepath = os.path.join(wandb.run.dir, 'model-best.h5')
        self.save_model = save_model
        self.log_weights = log_weights
        self.log_gradients = log_gradients
        self.training_data = training_data

        if self.training_data:
            if len(self.training_data) != 2:
                raise ValueError("training data must be a tuple of length two")

        # From Keras
        if mode not in ['auto', 'min', 'max']:
            print('WandbKerasCallback mode %s is unknown, '
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
        print(params)

    def set_model(self, model):
        self.model = model

    def on_epoch_begin(self, epoch, logs=None):
        pass

    def on_epoch_end(self, epoch, logs=None):
        # history
        row = {'epoch': epoch}
        row.update(logs)

        if self.log_weights:
            weights_metrics = self._log_weights()
            row.update(weights_metrics)

        if self.log_gradients:
            gradients_metrics = self._log_gradients()
            row.update(gradients_metrics)

        wandb.run.history.add(row)

        # summary
        self.current = logs.get(self.monitor)
        if self.current is None:    # validation data wasn't set
            #            print('Can save best model only with %s available, '
            #                  'skipping.' % (self.monitor))
            wandb.run.summary.update(row)
            return

        copied = copy.copy(row)
        if self.monitor_op(self.current, self.best):
            copied.pop('epoch')
            wandb.run.summary.update(copied)
            if self.save_model:
                self._save_model()

    def on_batch_begin(self, batch, logs=None):
        pass

    def on_batch_end(self, batch, logs=None):
        pass

    def on_train_begin(self, logs=None):
        pass

    def on_train_end(self, logs=None):
        pass

    def _log_weights(self):
        metrics = {}
        for layer in self.model.layers:
            weights = layer.get_weights()
            if len(weights) == 1:
                metrics[layer.name] = np.mean(weights[0])
            elif len(weights) == 2:
                metrics[layer.name + ":weights-mean"] = np.mean(weights[0])
                metrics[layer.name + ":bias-mean"] = np.mean(weights[1])
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
            metrics[weight.name.split(':')[0] + ":grad-mean"] = np.mean(grad)
            metrics[weight.name.split(':')[0] + ":grad-stddev"] = np.std(grad)
        return metrics

    def _save_model(self):
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
