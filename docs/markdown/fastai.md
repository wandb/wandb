---
description: wandb.fastai
---

# wandb.fastai
[source](https://github.com/wandb/client/blob/master/wandb/fastai/__init__.py#L0)

This module hooks fast.ai Learners to Weights & Biases through a callback.
Requested logged data can be configured through the callback constructor.

**Examples**:

 WandbCallback can be used when initializing the Learner::
 
```python
from wandb.fastai import WandbCallback
[...]
learn = Learner(data, ..., callback_fns=WandbCallback)
learn.fit(epochs)
```
 
 Custom parameters can be given using functools.partial::
 
```python
from wandb.fastai import WandbCallback
from functools import partial
[...]
learn = Learner(data, ..., callback_fns=partial(WandbCallback, ...))
learn.fit(epochs)
```
 
 Finally, it is possible to use WandbCallback only when starting training. In this case it must be instantiated::
 
```python
learn.fit(..., callbacks=WandbCallback(learn))
```
 
 or, with custom parameters::
 
```python
learn.fit(..., callbacks=WandbCallback(learn, ...))
```
 

## WandbCallback
[source](https://github.com/wandb/client/blob/master/wandb/fastai/__init__.py#L51)
```python
WandbCallback(self,
              learn,
              log='gradients',
              save_model=True,
              monitor=None,
              mode='auto',
              input_type=None,
              validation_data=None,
              predictions=36,
              seed=12345)
```

Automatically saves model topology, losses & metrics. Optionally logs weights, gradients, sample predictions and best trained model.

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
 

### WandbCallback.on_train_begin
[source](https://github.com/wandb/client/blob/master/wandb/fastai/__init__.py#L110)
```python
WandbCallback.on_train_begin(self, **kwargs)
```
Call watch method to log model topology, gradients & weights

### WandbCallback.on_epoch_end
[source](https://github.com/wandb/client/blob/master/wandb/fastai/__init__.py#L123)
```python
WandbCallback.on_epoch_end(self, epoch, smooth_loss, last_metrics, **kwargs)
```
Logs training loss, validation loss and custom metrics & log prediction samples & save model

### WandbCallback.on_train_end
[source](https://github.com/wandb/client/blob/master/wandb/fastai/__init__.py#L205)
```python
WandbCallback.on_train_end(self, **kwargs)
```
Load the best model.
