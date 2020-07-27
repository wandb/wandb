---
menu: main
title: Framework Documentation
---

<a name="wandb.framework.keras.keras"></a>
# wandb.framework.keras.keras

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/framework/keras/keras.py#L2)

keras init

<a name="wandb.framework.keras.keras.WandbCallback"></a>
## WandbCallback Objects

```python
class WandbCallback(keras.callbacks.Callback)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/framework/keras/keras.py#L158)

WandbCallback automatically integrates keras with wandb.

**Example**:

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


**Arguments**:

- `monitor` _str_ - name of metric to monitor.  Defaults to val_loss.
- `mode` _str_ - one of {"auto", "min", "max"}.
"min" - save model when monitor is minimized
"max" - save model when monitor is maximized
"auto" - try to guess when to save the model (default).
save_model:
True - save a model when monitor beats all previous epochs
False - don't save models
- `save_graph` - (boolean): if True save model graph to wandb (default: True).
- `save_weights_only` _boolean_ - if True, then only the model's weights will be
saved (`model.save_weights(filepath)`), else the full model
is saved (`model.save(filepath)`).
- `log_weights` - (boolean) if True save histograms of the model's layer's weights.
- `log_gradients` - (boolean) if True log histograms of the training gradients
- `training_data` - (tuple) Same format (X,y) as passed to model.fit.  This is needed
for calculating gradients - this is mandatory if `log_gradients` is `True`.
- `validate_data` - (tuple) Same format (X,y) as passed to model.fit.  A set of data
for wandb to visualize.  If this is set, every epoch, wandb will
make a small number of predictions and save the results for later visualization.
- `generator` _generator_ - a generator that returns validation data for wandb to visualize.  This
generator should return tuples (X,y).  Either validate_data or generator should
be set for wandb to visualize specific data examples.
- `validation_steps` _int_ - if `validation_data` is a generator, how many
steps to run the generator for the full validation set.
- `labels` _list_ - If you are visualizing your data with wandb this list of labels
will convert numeric output to understandable string if you are building a
multiclass classifier.  If you are making a binary classifier you can pass in
a list of two labels ["label for false", "label for true"].  If validate_data
and generator are both false, this won't do anything.
- `predictions` _int_ - the number of predictions to make for visualization each epoch, max
is 100.
- `input_type` _string_ - type of the model input to help visualization. can be one of:
("image", "images", "segmentation_mask").
- `output_type` _string_ - type of the model output to help visualziation. can be one of:
("image", "images", "segmentation_mask").
- `log_evaluation` _boolean_ - if True save a dataframe containing the full
validation results at the end of training.
- `class_colors` _[float, float, float]_ - if the input or output is a segmentation mask,
an array containing an rgb tuple (range 0-1) for each class.
- `log_batch_frequency` _integer_ - if None, callback will log every epoch.
If set to integer, callback will log training metrics every log_batch_frequency
batches.
- `log_best_prefix` _string_ - if None, no extra summary metrics will be saved.
If set to a string, the monitored metric and epoch will be prepended with this value
and stored as summary metrics.

<a name="wandb.framework.fastai"></a>
# wandb.framework.fastai

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/framework/fastai/__init__.py#L1)

This module hooks fast.ai Learners to Weights & Biases through a callback.
Requested logged data can be configured through the callback constructor.

**Examples**:

WandbCallback can be used when initializing the Learner::

```
from wandb.fastai import WandbCallback
[...]
learn = Learner(data, ..., callback_fns=WandbCallback)
learn.fit(epochs)
```

Custom parameters can be given using functools.partial::

```
from wandb.fastai import WandbCallback
from functools import partial
[...]
learn = Learner(data, ..., callback_fns=partial(WandbCallback, ...))
learn.fit(epochs)
```

Finally, it is possible to use WandbCallback only when starting
training. In this case it must be instantiated::

```
learn.fit(..., callbacks=WandbCallback(learn))
```

or, with custom parameters::

```
learn.fit(..., callbacks=WandbCallback(learn, ...))
```

<a name="wandb.framework.fastai.WandbCallback"></a>
## WandbCallback Objects

```python
class WandbCallback(TrackerCallback)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/framework/fastai/__init__.py#L51)

Automatically saves model topology, losses & metrics.
Optionally logs weights, gradients, sample predictions and best trained model.

**Arguments**:

- `learn` _fastai.basic_train.Learner_ - the fast.ai learner to hook.
- `log` _str_ - "gradients", "parameters", "all", or None. Losses & metrics are always logged.
- `save_model` _bool_ - save model at the end of each epoch. It will also load best model at the end of training.
- `monitor` _str_ - metric to monitor for saving best model. None uses default TrackerCallback monitor value.
- `mode` _str_ - "auto", "min" or "max" to compare "monitor" values and define best model.
- `input_type` _str_ - "images" or None. Used to display sample predictions.
- `validation_data` _list_ - data used for sample predictions if input_type is set.
- `predictions` _int_ - number of predictions to make if input_type is set and validation_data is None.
- `seed` _int_ - initialize random generator for sample predictions if input_type is set and validation_data is None.

<a name="wandb.framework.fastai.WandbCallback.on_train_begin"></a>
#### on\_train\_begin

```python
 | on_train_begin(**kwargs)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/framework/fastai/__init__.py#L109)

Call watch method to log model topology, gradients & weights

<a name="wandb.framework.fastai.WandbCallback.on_epoch_end"></a>
#### on\_epoch\_end

```python
 | on_epoch_end(epoch, smooth_loss, last_metrics, **kwargs)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/framework/fastai/__init__.py#L122)

Logs training loss, validation loss and custom metrics & log prediction samples & save model

<a name="wandb.framework.fastai.WandbCallback.on_train_end"></a>
#### on\_train\_end

```python
 | on_train_end(**kwargs)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/framework/fastai/__init__.py#L159)

Load the best model.

