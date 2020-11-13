---
title: Run
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

<a name="wandb.sdk.wandb_run.Run.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(config=None, settings=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L153)

<a name="wandb.sdk.wandb_run.Run.__setattr__"></a>
#### \_\_setattr\_\_

```python
 | __setattr__(attr, value)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L257)

<a name="wandb.sdk.wandb_run.Run.__getstate__"></a>
#### \_\_getstate\_\_

```python
 | __getstate__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L327)

<a name="wandb.sdk.wandb_run.Run.__setstate__"></a>
#### \_\_setstate\_\_

```python
 | __setstate__(state)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L330)

<a name="wandb.sdk.wandb_run.Run.dir"></a>
#### dir

```python
 | @property
 | dir()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L334)

str: The directory where all of the files associated with the run are
placed.

<a name="wandb.sdk.wandb_run.Run.config"></a>
#### config

```python
 | @property
 | config()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L341)

(`Config`): A config object (similar to a nested dict) of key
value pairs associated with the hyperparameters of the run.

<a name="wandb.sdk.wandb_run.Run.config_static"></a>
#### config\_static

```python
 | @property
 | config_static()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L348)

<a name="wandb.sdk.wandb_run.Run.name"></a>
#### name

```python
 | @property
 | name()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L352)

str: the display name of the run. It does not need to be unique
and ideally is descriptive.

<a name="wandb.sdk.wandb_run.Run.name"></a>
#### name

```python
 | @name.setter
 | name(name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L362)

<a name="wandb.sdk.wandb_run.Run.notes"></a>
#### notes

```python
 | @property
 | notes()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L368)

str: notes associated with the run. Notes can be a multiline string
and can also use markdown and latex equations inside $$ like $\\{x}

<a name="wandb.sdk.wandb_run.Run.notes"></a>
#### notes

```python
 | @notes.setter
 | notes(notes)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L378)

<a name="wandb.sdk.wandb_run.Run.tags"></a>
#### tags

```python
 | @property
 | tags() -> Optional[Tuple]
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L384)

Tuple[str]: tags associated with the run

<a name="wandb.sdk.wandb_run.Run.tags"></a>
#### tags

```python
 | @tags.setter
 | tags(tags: Sequence)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L392)

<a name="wandb.sdk.wandb_run.Run.id"></a>
#### id

```python
 | @property
 | id()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L398)

str: the run_id associated with the run

<a name="wandb.sdk.wandb_run.Run.sweep_id"></a>
#### sweep\_id

```python
 | @property
 | sweep_id()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L403)

(str, optional): the sweep id associated with the run or None

<a name="wandb.sdk.wandb_run.Run.path"></a>
#### path

```python
 | @property
 | path()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L410)

str: the path to the run [entity]/[project]/[run_id]

<a name="wandb.sdk.wandb_run.Run.start_time"></a>
#### start\_time

```python
 | @property
 | start_time()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L419)

int: the unix time stamp in seconds when the run started

<a name="wandb.sdk.wandb_run.Run.starting_step"></a>
#### starting\_step

```python
 | @property
 | starting_step()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L427)

int: the first step of the run

<a name="wandb.sdk.wandb_run.Run.resumed"></a>
#### resumed

```python
 | @property
 | resumed()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L435)

bool: whether or not the run was resumed

<a name="wandb.sdk.wandb_run.Run.step"></a>
#### step

```python
 | @property
 | step()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L443)

int: step counter

Every time you call wandb.log() it will by default increment the step
counter.

<a name="wandb.sdk.wandb_run.Run.project_name"></a>
#### project\_name

```python
 | project_name(api=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L451)

<a name="wandb.sdk.wandb_run.Run.mode"></a>
#### mode

```python
 | @property
 | mode()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L456)

For compatibility with 0.9.x and earlier, deprecate eventually.

<a name="wandb.sdk.wandb_run.Run.offline"></a>
#### offline

```python
 | @property
 | offline()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L461)

<a name="wandb.sdk.wandb_run.Run.group"></a>
#### group

```python
 | @property
 | group()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L465)

str: name of W&B group associated with run.

Setting a group helps the W&B UI organize runs in a sensible way.

If you are doing a distributed training you should give all of the
runs in the training the same group.
If you are doing crossvalidation you should give all the crossvalidation
folds the same group.

<a name="wandb.sdk.wandb_run.Run.job_type"></a>
#### job\_type

```python
 | @property
 | job_type()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L479)

<a name="wandb.sdk.wandb_run.Run.project"></a>
#### project

```python
 | @property
 | project()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L484)

str: name of W&B project associated with run.

<a name="wandb.sdk.wandb_run.Run.get_url"></a>
#### get\_url

```python
 | get_url()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L488)

Returns: (str, optional): url for the W&B run or None if the run
is offline

<a name="wandb.sdk.wandb_run.Run.get_project_url"></a>
#### get\_project\_url

```python
 | get_project_url()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L496)

Returns: (str, optional): url for the W&B project associated with
the run or None if the run is offline

<a name="wandb.sdk.wandb_run.Run.get_sweep_url"></a>
#### get\_sweep\_url

```python
 | get_sweep_url()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L504)

Returns: (str, optional): url for the sweep associated with the run
or None if there is no associated sweep or the run is offline.

<a name="wandb.sdk.wandb_run.Run.url"></a>
#### url

```python
 | @property
 | url()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L513)

str: name of W&B url associated with run.

<a name="wandb.sdk.wandb_run.Run.entity"></a>
#### entity

```python
 | @property
 | entity()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L518)

str: name of W&B entity associated with run. Entity is either
a user name or an organization name.

<a name="wandb.sdk.wandb_run.Run._repr_mimebundle_"></a>
#### \_repr\_mimebundle\_

```python
 | _repr_mimebundle_(include=None, exclude=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L531)

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

<a name="wandb.sdk.wandb_run.Run.save"></a>
#### save

```python
 | save(glob_str: Optional[str] = None, base_path: Optional[str] = None, policy: str = "live")
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L807)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L893)

<a name="wandb.sdk.wandb_run.Run.finish"></a>
#### finish

```python
 | finish(exit_code=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L902)

Marks a run as finished, and finishes uploading all data.  This is
used when creating multiple runs in the same process.  We automatically
call this method when your script exits.

<a name="wandb.sdk.wandb_run.Run.join"></a>
#### join

```python
 | join(exit_code=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L916)

Deprecated alias for finish() - please use finish

<a name="wandb.sdk.wandb_run.Run.plot_table"></a>
#### plot\_table

```python
 | plot_table(vega_spec_name, data_table, fields, string_fields=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L920)

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

<a name="wandb.sdk.wandb_run.Run.watch"></a>
#### watch

```python
 | watch(models, criterion=None, log="gradients", log_freq=100, idx=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L1549)

<a name="wandb.sdk.wandb_run.Run.use_artifact"></a>
#### use\_artifact

```python
 | use_artifact(artifact_or_name, type=None, aliases=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L1552)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L1607)

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

<a name="wandb.sdk.wandb_run.Run.alert"></a>
#### alert

```python
 | alert(title, text, level=None, wait_duration=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L1661)

Launch an alert with the given title and text.

**Arguments**:

- `title` _str_ - The title of the alert, must be less than 64 characters long
- `text` _str_ - The text body of the alert
- `level` _str or wandb.AlertLevel, optional_ - The alert level to use, either: "INFO", "WARN", or "ERROR"
- `wait_duration` _int, float, or timedelta, optional_ - The time to wait (in seconds) before sending another alert
with this title

<a name="wandb.sdk.wandb_run.Run.__enter__"></a>
#### \_\_enter\_\_

```python
 | __enter__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L1697)

<a name="wandb.sdk.wandb_run.Run.__exit__"></a>
#### \_\_exit\_\_

```python
 | __exit__(exc_type, exc_val, exc_tb)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_run.py#L1700)

