---
title: Log
---

<a name="wandb.sdk.wandb_run"></a>
# wandb.sdk.wandb\_run

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L4)

<a name="wandb.sdk.wandb_run.Run"></a>
## Run Objects

```python
class Run(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L132)

The run object corresponds to a single execution of your script,
typically this is an ML experiment. Create a run with wandb.init().

In distributed training, use wandb.init() to create a run for each process,
and set the group argument to organize runs into a larger experiment.

Currently there is a parallel Run object in the wandb.Api. Eventually these
two objects will be merged.

**Attributes**:

- `history` _`History`_ - Time series values, created with wandb.log().
History can contain scalar values, rich media, or even custom plots
across multiple steps.
- `summary` _`Summary`_ - Single values set for each wandb.log() key. By
default, summary is set to the last value logged. You can manually
set summary to the best value, like max accuracy, instead of the
final value.

<a name="wandb.sdk.wandb_run.Run.log"></a>
#### log

```python
 | log(data, step=None, commit=None, sync=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L672)

Log a dict to the global run's history.

wandb.log can be used to log everything from scalars to histograms, media
and matplotlib plots.

The most basic usage is wandb.log({'train-loss': 0.5, 'accuracy': 0.9}).
This will save a history row associated with the run with train-loss=0.5
and accuracy=0.9. The history values can be plotted on app.wandb.ai or
on a local server. The history values can also be downloaded through
the wandb API.

Logging a value will update the summary values for any metrics logged.
The summary values will appear in the run table at app.wandb.ai or
a local server. If a summary value is manually set with for example
wandb.run.summary["accuracy"] = 0.9 wandb.log will no longer automatically
update the run's accuracy.

Logging values don't have to be scalars. Logging any wandb object is supported.
For example wandb.log({"example": wandb.Image("myimage.jpg")}) will log an
example image which will be displayed nicely in the wandb UI. See
https://docs.wandb.com/library/reference/data_types for all of the different
supported types.

Logging nested metrics is encouraged and is supported in the wandb API, so
you could log multiple accuracy values with wandb.log({'dataset-1':
{'acc': 0.9, 'loss': 0.3} ,'dataset-2': {'acc': 0.8, 'loss': 0.2}})
and the metrics will be organized in the wandb UI.

W&B keeps track of a global step so logging related metrics together is
encouraged, so by default each time wandb.log is called a global step
is incremented. If it's inconvenient to log related metrics together
calling wandb.log({'train-loss': 0.5, commit=False}) and then
wandb.log({'accuracy': 0.9}) is equivalent to calling
wandb.log({'train-loss': 0.5, 'accuracy': 0.9})

wandb.log is not intended to be called more than a few times per second.
If you want to log more frequently than that it's better to aggregate
the data on the client side or you may get degraded performance.

**Arguments**:

- `row` _dict, optional_ - A dict of serializable python objects i.e str,
ints, floats, Tensors, dicts, or wandb.data_types
- `commit` _boolean, optional_ - Save the metrics dict to the wandb server
and increment the step.  If false wandb.log just updates the current
metrics dict with the row argument and metrics won't be saved until
wandb.log is called with commit=True.
- `step` _integer, optional_ - The global step in processing. This persists
any non-committed earlier steps but defaults to not committing the
specified step.
- `sync` _boolean, True_ - This argument is deprecated and currently doesn't
change the behaviour of wandb.log


**Examples**:

Basic usage
```
- `wandb.log({'accuracy'` - 0.9, 'epoch': 5})
```

Incremental logging
```
- `wandb.log({'loss'` - 0.2}, commit=False)
# Somewhere else when I'm ready to report this step:
- `wandb.log({'accuracy'` - 0.8})
```

Histogram
```
- `wandb.log({"gradients"` - wandb.Histogram(numpy_array_or_sequence)})
```

Image
```
- `wandb.log({"examples"` - [wandb.Image(numpy_array_or_pil, caption="Label")]})
```

Video
```
- `wandb.log({"video"` - wandb.Video(numpy_array_or_video_path, fps=4,
format="gif")})
```

Matplotlib Plot
```
- `wandb.log({"chart"` - plt})
```

PR Curve
```
- `wandb.log({'pr'` - wandb.plots.precision_recall(y_test, y_probas, labels)})
```

3D Object
```
wandb.log({"generated_samples":
[wandb.Object3D(open("sample.obj")),
wandb.Object3D(open("sample.gltf")),
wandb.Object3D(open("sample.glb"))]})
```

For more examples, see https://docs.wandb.com/library/log


**Raises**:

wandb.Error - if called before wandb.init
ValueError - if invalid data is passed

