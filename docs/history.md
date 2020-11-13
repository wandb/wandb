---
title: History
---

<a name="wandb.sdk.wandb_history"></a>
# wandb.sdk.wandb\_history

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_history.py#L3)

History tracks logged data over time. To use history from your script, call
wandb.log({"key": value}) at a single time step or multiple times in your
training loop. This generates a time series of saved scalars or media that is
saved to history.

In the UI, if you log a scalar at multiple timesteps W&B will render these
history metrics as line plots by default. If you log a single value in history,
compare across runs with a bar chart.

It's often useful to track a full time series as well as a single summary value.
For example, accuracy at every step in History and best accuracy in Summary.
By default, Summary is set to the final value of History.

<a name="wandb.sdk.wandb_history.History"></a>
## History Objects

```python
class History(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_history.py#L23)

Time series data for Runs. This is essentially a list of dicts where each
dict is a set of summary statistics logged.

<a name="wandb.sdk.wandb_history.History.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(run)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_history.py#L28)

<a name="wandb.sdk.wandb_history.History.start_time"></a>
#### start\_time

```python
 | @property
 | start_time()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_history.py#L63)

<a name="wandb.sdk.wandb_history.History.add"></a>
#### add

```python
 | add(d)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_history.py#L66)

<a name="wandb.sdk.wandb_history.History.torch"></a>
#### torch

```python
 | @property
 | torch()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_history.py#L70)

