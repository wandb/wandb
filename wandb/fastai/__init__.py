'''W&B Callback for fast.ai

This module hooks fast.ai Learners to Weights & Biases through a callback.
Requested logged data can be configured through the callback constructor.

Examples:
    WandbCallback can be used when initializing the Learner::

        from wandb.fastai import WandbCallback
        [...]
        learn = Learner(data, ..., callback_fns=WandbCallback)
        learn.fit(epochs)
    
    Custom parameters can be given using functools.partial::

        from wandb.fastai import WandbCallback
        from functools import partial
        [...]
        learn = Learner(data,
                    callback_fns=partial(WandbCallback, ...),
                    ...)  # add "path=wandb.run.dir" if saving model
        learn.fit(epochs)

    Finally, it is possible to use WandbCallback only when starting
    training. In this case it must be instantiated::

        learn.fit(..., callbacks=WandbCallback())

    or, with custom parameters::

        learn.fit(..., callbacks=WandBCallback(learn, ...))
'''
import wandb
import matplotlib
matplotlib.use('Agg')  # non-interactive back-end (avoid issues with tkinter)
import matplotlib.pyplot as plt
from fastai.callbacks import TrackerCallback
from pathlib import Path


class WandbCallback(TrackerCallback):

    # Record if watch has been called previously (even in another instance)
    watch_called = False

    def __init__(self,
                 learn,
                 log=None,
                 show_results=False,
                 save_model=False,
                 monitor='val_loss',
                 mode='auto'):
        """WandB fast.ai Callback

        Automatically saves model topology, losses & metrics.
        Optionally logs weights, gradients, sample predictions and best trained model.

        Args:
            learn (fastai.basic_train.Learner): the fast.ai learner to hook.
            log (str): One of "gradients", "parameters", "all", or None. Losses & metrics are always logged.
            show_results (bool): whether we want to display sample predictions, works only with images at the moment
            save_model (bool): save model at the end of each epoch.
            monitor (str): metric to monitor for saving best model.
            mode (str): "auto", "min" or "max" to compare "monitor" values and define best model.
        """

        # Check if wandb.init has been called
        if wandb.run is None:
            raise ValueError(
                'You must call wandb.init() before WandbCallback()')

        # Adapted from fast.ai "SaveModelCallback"
        super().__init__(learn, monitor=monitor, mode=mode)
        self.save_model = save_model
        self.model_path = Path(wandb.run.dir) / 'bestmodel.pth'

        self.log = log
        self.show_results = show_results
        self.best = None

    def on_train_begin(self, **kwargs):
        "Call watch method to log model topology, gradients & weights"

        # Set self.best, method inherited from "TrackerCallback" by "SaveModelCallback"
        super().on_train_begin()

        # Ensure we don't call "watch" multiple times
        if not WandbCallback.watch_called:
            WandbCallback.watch_called = True

            # Logs model topology and optionally gradients and weights
            wandb.watch(self.learn.model, log=self.log)

    def on_epoch_end(self, epoch, smooth_loss, last_metrics, **kwargs):
        "Logs training loss, validation loss and custom metrics & log prediction samples & save model"

        if self.save_model:
            # Adapted from fast.ai "SaveModelCallback"
            current = self.get_monitor_value()
            if current is not None and self.operator(current, self.best):
                print(
                    'Better model found at epoch {} with {} value: {}.'.format(epoch, self.monitor, current)
                )
                self.best = current

                # Section modified to save within wandb folder
                with self.model_path.open('wb') as model_file:
                    self.learn.save(model_file)

        # Log sample predictions
        if self.show_results:
            self.learn.show_results()  # pyplot display of sample predictions
            wandb.log({"Prediction Samples": plt}, commit=False)

        # Log losses & metrics
        # Adapted from fast.ai "CSVLogger"
        logs = {
            name: stat
            for name, stat in list(
                zip(self.learn.recorder.names, [epoch, smooth_loss] +
                    last_metrics))[1:]
        }
        wandb.log(logs)

        # We can now close results figure
        if self.show_results:
            plt.close('all')

    def on_train_end(self, **kwargs):
        "Load the best model."

        if self.save_model:
            # Adapted from fast.ai "SaveModelCallback"
            if self.model_path.is_file():
                with self.model_path.open('rb') as model_file:
                    self.learn.load(model_file, purge=False)
                    print('Loaded best saved model from {}'.format(self.model_path))
