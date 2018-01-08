import copy
import operator
import os

import wandb

# Fully implemented here so we don't have to pull in keras as a dependency.
# However, if the user is using this, they necessarily have Keras installed. So we
# could probably selectively build this class only when the user requests it,
# knowing that keras is available.
#
# Or have a separate lib "wandb-keras", then we could use the appropriate Keras
# pieces


class WandbKerasCallback(object):
    """WandB Keras Callback.

    Automatically saves wandb-history.csv and wandb-summary.csv, both tracking
    keras metrics.
    """

    def __init__(self, monitor='val_loss', verbose=0, mode='auto',
                 save_weights_only=False):
        """Constructor.

        Args:
            See keras.ModelCheckpoint for other definitions of other
                arguments.
        """
        if wandb.run is None:
            raise wandb.Error(
                'You must call wandb.init() before WandbKerasCallback()')
        self.validation_data = None

        self.monitor = monitor
        self.verbose = verbose
        self.save_weights_only = save_weights_only

        self.filepath = os.path.join(wandb.run.dir, 'model-best.h5')

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

    def set_model(self, model):
        self.model = model

    def on_epoch_begin(self, epoch, logs=None):
        pass

    def on_epoch_end(self, epoch, logs=None):
        # history
        row = {'epoch': epoch}
        row.update(logs)
        wandb.run.history.add(row)

        # summary
        current = logs.get(self.monitor)
        if current is None:    # validation data wasn't set
#            print('Can save best model only with %s available, '
#                  'skipping.' % (self.monitor))
            wandb.run.summary.update(row)
            return

        copied = copy.copy(row)
        if self.monitor_op(current, self.best):
            copied.pop('epoch')
            wandb.run.summary.update(copied)
            if self.verbose > 0:
                print('Epoch %05d: %s improved from %0.5f to %0.5f,'
                      ' saving model to %s'
                      % (epoch, self.monitor, self.best,
                         current, self.filepath))
            self.best = current
            try:
                if self.save_weights_only:
                    self.model.save_weights(self.filepath, overwrite=True)
                else:
                    self.model.save(self.filepath, overwrite=True)
            except ImportError:
                print("Warning: Can't save model without h5py installed")
                
    def on_batch_begin(self, batch, logs=None):
        pass

    def on_batch_end(self, batch, logs=None):
        pass

    def on_train_begin(self, logs=None):
        pass

    def on_train_end(self, logs=None):
        pass
