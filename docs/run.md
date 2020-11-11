---
menu: main
title: Run
---

<a name="wandb.sdk.wandb_run"></a>
# wandb.sdk.wandb\_run

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L3)

The run object corresponds to a single execution of your script,
typically this is an ML experiment. Create a run with wandb.init().

<a name="wandb.sdk.wandb_run.Run"></a>
## Run Objects

```python
class Run(RunBase)
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L241)

Defines a wandb run, which typically corresponds to an ML experiment.

A run is created with wandb.init()

If you do distributed training, each process should be in its own run and
the group should be set in wandb.init to link the runs together.

There is a parallel Run object in wandb's API, eventually it will be merged
with this object.

**Attributes**:

- `summary` _#Summary_ - summary statistics collected as training code
runs.
- `history` _#History_ - history of data logged with wandb.log associated
with run.

<a name="wandb.sdk.wandb_run.Run.dir"></a>
#### dir

```python
 | @property
 | dir()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L440)

str: The directory where all of the files associated with the run are
placed.

<a name="wandb.sdk.wandb_run.Run.config"></a>
#### config

```python
 | @property
 | config()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L447)

(:obj:`Config`): A config object (similar to a nested dict) of key
value pairs associated with the hyperparameters of the run.

<a name="wandb.sdk.wandb_run.Run.name"></a>
#### name

```python
 | @property
 | name()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L458)

str: the display name of the run. It does not need to be unique
and ideally is descriptive.

<a name="wandb.sdk.wandb_run.Run.notes"></a>
#### notes

```python
 | @property
 | notes()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L474)

str: notes associated with the run. Notes can be a multiline string
and can also use markdown and latex equations inside $$ like $\\{x}

<a name="wandb.sdk.wandb_run.Run.tags"></a>
#### tags

```python
 | @property
 | tags() -> Optional[Tuple]
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L490)

Tuple[str]: tags associated with the run

<a name="wandb.sdk.wandb_run.Run.id"></a>
#### id

```python
 | @property
 | id()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L504)

str: the run_id associated with the run

<a name="wandb.sdk.wandb_run.Run.sweep_id"></a>
#### sweep\_id

```python
 | @property
 | sweep_id()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L509)

(str, optional): the sweep id associated with the run or None

<a name="wandb.sdk.wandb_run.Run.path"></a>
#### path

```python
 | @property
 | path()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L516)

str: the path to the run [entity]/[project]/[run_id]

<a name="wandb.sdk.wandb_run.Run.start_time"></a>
#### start\_time

```python
 | @property
 | start_time()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L525)

int: the unix time stamp in seconds when the run started

<a name="wandb.sdk.wandb_run.Run.starting_step"></a>
#### starting\_step

```python
 | @property
 | starting_step()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L533)

int: the first step of the run

<a name="wandb.sdk.wandb_run.Run.resumed"></a>
#### resumed

```python
 | @property
 | resumed()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L541)

bool: whether or not the run was resumed

<a name="wandb.sdk.wandb_run.Run.step"></a>
#### step

```python
 | @property
 | step()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L549)

int: step counter

Every time you call wandb.log() it will by default increment the step
counter.

<a name="wandb.sdk.wandb_run.Run.mode"></a>
#### mode

```python
 | @property
 | mode()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L562)

For compatibility with 0.9.x and earlier, deprecate eventually.

<a name="wandb.sdk.wandb_run.Run.group"></a>
#### group

```python
 | @property
 | group()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L571)

str: name of W&B group associated with run.

Setting a group helps the W&B UI organize runs in a sensible way.

If you are doing a distributed training you should give all of the
runs in the training the same group.
If you are doing crossvalidation you should give all the crossvalidation
folds the same group.

<a name="wandb.sdk.wandb_run.Run.project"></a>
#### project

```python
 | @property
 | project()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L590)

str: name of W&B project associated with run.

<a name="wandb.sdk.wandb_run.Run.get_url"></a>
#### get\_url

```python
 | get_url()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L594)

Returns: (str, optional): url for the W&B run or None if the run
is offline

<a name="wandb.sdk.wandb_run.Run.get_project_url"></a>
#### get\_project\_url

```python
 | get_project_url()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L602)

Returns: (str, optional): url for the W&B project associated with
the run or None if the run is offline

<a name="wandb.sdk.wandb_run.Run.get_sweep_url"></a>
#### get\_sweep\_url

```python
 | get_sweep_url()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L610)

Returns: (str, optional): url for the sweep associated with the run
or None if there is no associated sweep or the run is offline.

<a name="wandb.sdk.wandb_run.Run.url"></a>
#### url

```python
 | @property
 | url()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L619)

str: name of W&B url associated with run.

<a name="wandb.sdk.wandb_run.Run.entity"></a>
#### entity

```python
 | @property
 | entity()
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L624)

str: name of W&B entity associated with run. Entity is either
a user name or an organization name.

<a name="wandb.sdk.wandb_run.Run.log"></a>
#### log

```python
 | log(data, step=None, commit=None, sync=None)
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L778)

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

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L913)

Ensure all files matching *glob_str* are synced to wandb with the policy specified.

**Arguments**:

- `glob_str` _string_ - a relative or absolute path to a unix glob or regular
path.  If this isn't specified the method is a noop.
- `base_path` _string_ - the base path to run the glob relative to
- `policy` _string_ - on of "live", "now", or "end"
- `live` - upload the file as it changes, overwriting the previous version
- `now` - upload the file once now
- `end` - only upload file when the run ends

<a name="wandb.sdk.wandb_run.Run.restore"></a>
#### restore

```python
 | restore(name: str, run_path: Optional[str] = None, replace: bool = False, root: Optional[str] = None)
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L999)

Downloads the specified file from cloud storage into the current run directory
if it doesn't exist.

**Arguments**:

- `name` - the name of the file
- `run_path` - optional path to a different run to pull files from
- `replace` - whether to download the file even if it already exists locally
- `root` - the directory to download the file to.  Defaults to the current
directory or the run directory if wandb.init was called.


**Returns**:

None if it can't find the file, otherwise a file object open for reading


**Raises**:

wandb.CommError if it can't find the run
ValueError if the file is not found

<a name="wandb.sdk.wandb_run.Run.finish"></a>
#### finish

```python
 | finish(exit_code=None)
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L1040)

Marks a run as finished, and finishes uploading all data.  This is
used when creating multiple runs in the same process.  We automatically
call this method when your script exits.

<a name="wandb.sdk.wandb_run.Run.join"></a>
#### join

```python
 | join(exit_code=None)
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L1054)

Deprecated alias for finish() - please use finish

<a name="wandb.sdk.wandb_run.Run.plot_table"></a>
#### plot\_table

```python
 | plot_table(vega_spec_name, data_table, fields, string_fields=None)
```

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L1058)

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

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L1690)

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

[[view_source]](https://github.com/wandb/client/blob/a168eae09196232da9bd06071a3771e2d076cc6a/wandb/sdk/wandb_run.py#L1745)

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

A :obj:`Artifact` object.

