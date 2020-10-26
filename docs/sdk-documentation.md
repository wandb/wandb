---
menu: main
title: SDK Documentation
---

<a name="wandb"></a>
# wandb

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/__init__.py#L2)

Wandb is a library to help track machine learning experiments.

For more information on wandb see https://docs.wandb.com.

The most commonly used functions/objects are:
- wandb.init — initialize a new run at the top of your training script
- wandb.config — track hyperparameters
- wandb.log — log metrics over time within your training loop
- wandb.save — save files in association with your run, like model weights
- wandb.restore — restore the state of your code when you ran a given run

For examples usage, see https://docs.wandb.com/library/example-projects

<a name="wandb.sdk.wandb_run"></a>
# wandb.sdk.wandb\_run

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L3)

Run - Run object.

Manage wandb run.

<a name="wandb.sdk.wandb_run.RunStatusChecker"></a>
## RunStatusChecker Objects

```python
class RunStatusChecker(object)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L97)

Periodically polls the background process for relevant updates.

For now, we just use this to figure out if the user has requested a stop.

<a name="wandb.sdk.wandb_run.Run"></a>
## Run Objects

```python
class Run(RunBase)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L242)

<a name="wandb.sdk.wandb_run.Run.mode"></a>
#### mode

```python
 | @property
 | mode()
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L523)

For compatibility with 0.9.x and earlier, deprecate eventually.

<a name="wandb.sdk.wandb_run.Run.log"></a>
#### log

```python
 | log(data, step=None, commit=None, sync=None)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L720)

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

<a name="wandb.sdk.wandb_run.Run.save"></a>
#### save

```python
 | save(glob_str: Optional[str] = None, base_path: Optional[str] = None, policy: str = "live")
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L855)

Ensure all files matching *glob_str* are synced to wandb with the policy specified.

**Arguments**:

- `glob_str` _string_ - a relative or absolute path to a unix glob or regular
path.  If this isn't specified the method is a noop.
- `base_path` _string_ - the base path to run the glob relative to
- `policy` _string_ - on of "live", "now", or "end"
- `live` - upload the file as it changes, overwriting the previous version
- `now` - upload the file once now
- `end` - only upload file when the run ends

<a name="wandb.sdk.wandb_run.Run.finish"></a>
#### finish

```python
 | finish(exit_code=None)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L950)

Marks a run as finished, and finishes uploading all data.  This is
used when creating multiple runs in the same process.  We automatically
call this method when your script exits.

<a name="wandb.sdk.wandb_run.Run.plot_table"></a>
#### plot\_table

```python
 | plot_table(vega_spec_name, data_table, fields, string_fields=None)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L967)

Creates a custom plot on a table.

**Arguments**:

- `vega_spec_name` - the name of the spec for the plot
- `table_key` - the key used to log the data table
- `data_table` - a wandb.Table object containing the data to
be used on the visualization
- `fields` - a dict mapping from table keys to fields that the custom
visualization needs
- `string_fields` - a dict that provides values for any string constants
the custom visualization needs

<a name="wandb.sdk.wandb_run.Run.use_artifact"></a>
#### use\_artifact

```python
 | use_artifact(artifact_or_name, type=None, aliases=None)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L1599)

Declare an artifact as an input to a run, call `download` or `file` on \
the returned object to get the contents locally.

**Arguments**:

- `artifact_or_name` _str or Artifact_ - An artifact name.
May be prefixed with entity/project. Valid names
can be in the following forms:
name:version
name:alias
digest
You can also pass an Artifact object created by calling `wandb.Artifact`
- `type` _str, optional_ - The type of artifact to use.
- `aliases` _list, optional_ - Aliases to apply to this artifact

**Returns**:

A `Artifact` object.

<a name="wandb.sdk.wandb_run.Run.log_artifact"></a>
#### log\_artifact

```python
 | log_artifact(artifact_or_path, name=None, type=None, aliases=None)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L1654)

Declare an artifact as output of a run.

**Arguments**:

- `artifact_or_path` _str or Artifact_ - A path to the contents of this artifact,
can be in the following forms:
/local/directory
/local/directory/file.txt
s3://bucket/path
You can also pass an Artifact object created by calling
`wandb.Artifact`.
- `name` _str, optional_ - An artifact name. May be prefixed with entity/project.
Valid names can be in the following forms:
name:version
name:alias
digest
This will default to the basename of the path prepended with the current
run id  if not specified.
- `type` _str_ - The type of artifact to log, examples include "dataset", "model"
- `aliases` _list, optional_ - Aliases to apply to this artifact,
defaults to ["latest"]

**Returns**:

A `Artifact` object.

<a name="wandb.sdk.wandb_run.restore"></a>
#### restore

```python
restore(name: str, run_path: Optional[str] = None, replace: bool = False, root: Optional[str] = None)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L1722)

Downloads the specified file from cloud storage into the current directory
or run directory.  By default this will only download the file if it doesn't
already exist.

**Arguments**:

- `name` - the name of the file
- `run_path` - optional path to a run to pull files from, i.e. username/project_name/run_id
if wandb.init has not been called, this is required.
- `replace` - whether to download the file even if it already exists locally
- `root` - the directory to download the file to.  Defaults to the current
directory or the run directory if wandb.init was called.


**Returns**:

None if it can't find the file, otherwise a file object open for reading


**Raises**:

wandb.CommError if we can't connect to the wandb backend
ValueError if the file is not found or can't find run_path

<a name="wandb.sdk.wandb_run.WriteSerializingFile"></a>
## WriteSerializingFile Objects

```python
class WriteSerializingFile(object)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_run.py#L1790)

Wrapper for a file object that serializes writes.

<a name="wandb.sdk.wandb_init"></a>
# wandb.sdk.wandb\_init

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_init.py#L3)

init.

<a name="wandb.sdk.wandb_init._WandbInit"></a>
## \_WandbInit Objects

```python
class _WandbInit(object)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_init.py#L46)

<a name="wandb.sdk.wandb_init._WandbInit.setup"></a>
#### setup

```python
 | setup(kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_init.py#L58)

Complete setup for wandb.init().

This includes parsing all arguments, applying them with settings and enabling
logging.

<a name="wandb.sdk.wandb_init.init"></a>
#### init

```python
init(job_type: Optional[str] = None, dir=None, config: Union[Dict, None] = None, project: Optional[str] = None, entity: Optional[str] = None, reinit: bool = None, tags: Optional[Sequence] = None, group: Optional[str] = None, name: Optional[str] = None, notes: Optional[str] = None, magic: Union[dict, str, bool] = None, config_exclude_keys=None, config_include_keys=None, anonymous: Optional[str] = None, mode: Optional[str] = None, allow_val_change: Optional[bool] = None, resume: Optional[Union[bool, str]] = None, force: Optional[bool] = None, tensorboard=None, sync_tensorboard=None, monitor_gym=None, save_code=None, id=None, settings: Union[Settings, Dict[str, Any], None] = None) -> RunBase
```

[[view_source]](https://github.com/wandb/client/blob/4345bddbc27a0c416a78ded5324b48e1d7aa0201/wandb/sdk/wandb_init.py#L421)

Initialize a wandb Run.

**Arguments**:

- `entity` - alias for team.
- `team` - personal user or team to use for Run.
- `project` - project name for the Run.


**Raises**:

- `Exception` - if problem.


**Returns**:

wandb Run object

