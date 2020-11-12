---
title: SDK Documentation
---

<a name="wandb"></a>
# wandb

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/__init__.py#L2)

Wandb is a library to help track machine learning experiments.

For more information on wandb see https://docs.wandb.com.

The most commonly used functions/objects are:
- wandb.init — initialize a new run at the top of your training script
- wandb.config — track hyperparameters
- wandb.log — log metrics over time within your training loop
- wandb.save — save files in association with your run, like model weights
- wandb.restore — restore the state of your code when you ran a given run

For examples usage, see https://docs.wandb.com/library/example-projects

<a name="wandb.sdk.wandb_alerts"></a>
# wandb.sdk.wandb\_alerts

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_alerts.py#L1)

<a name="wandb.sdk.wandb_artifacts"></a>
# wandb.sdk.wandb\_artifacts

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L2)

<a name="wandb.sdk.wandb_artifacts.Artifact"></a>
## Artifact Objects

```python
class Artifact(object)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L69)

An artifact object you can write files into, and pass to log_artifact.

<a name="wandb.sdk.wandb_artifacts.Artifact.add"></a>
#### add

```python
 | add(obj, name)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L229)

Adds `obj` to the artifact, located at `name`. You can use Artifact#get(`name`) after downloading
the artifact to retrieve this object.

**Arguments**:

- `obj` _wandb.Media_ - The object to save in an artifact
- `name` _str_ - The path to save

<a name="wandb.sdk.wandb_artifacts.Artifact.get_added_local_path_name"></a>
#### get\_added\_local\_path\_name

```python
 | get_added_local_path_name(local_path)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L278)

If local_path was already added to artifact, return its internal name.

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1"></a>
## ArtifactManifestV1 Objects

```python
class ArtifactManifestV1(ArtifactManifest)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L328)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.to_manifest_json"></a>
#### to\_manifest\_json

```python
 | to_manifest_json()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L368)

This is the JSON that's stored in wandb_manifest.json

If include_local is True we also include the local paths to files. This is
used to represent an artifact that's waiting to be saved on the current
system. We don't need to include the local paths in the artifact manifest
contents.

<a name="wandb.sdk.wandb_artifacts.TrackingHandler"></a>
## TrackingHandler Objects

```python
class TrackingHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L636)

<a name="wandb.sdk.wandb_artifacts.TrackingHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L637)

Tracks paths as is, with no modification or special processing. Useful
when paths being tracked are on file systems mounted at a standardized
location.

For example, if the data to track is located on an NFS share mounted on
/data, then it is sufficient to just track the paths.

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler"></a>
## LocalFileHandler Objects

```python
class LocalFileHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L682)

Handles file:// references

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L686)

Tracks files or directories on a local filesystem. Directories
are expanded to create an entry for each file contained within.

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler"></a>
## WBArtifactHandler Objects

```python
class WBArtifactHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L1172)

Handles loading and storing Artifact reference-type files

<a name="wandb.sdk.wandb_config"></a>
# wandb.sdk.wandb\_config

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_config.py#L3)

config.

<a name="wandb.sdk.wandb_config.Config"></a>
## Config Objects

```python
class Config(object)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_config.py#L28)

Config object

Config objects are intended to hold all of the hyperparameters associated with
a wandb run and are saved with the run object when wandb.init is called.

We recommend setting wandb.config once at the top of your training experiment or
setting the config as a parameter to init, ie. wandb.init(config=my_config_dict)

You can create a file called config-defaults.yaml, and it will automatically be
loaded into wandb.config. See https://docs.wandb.com/library/config#file-based-configs.

You can also load a config YAML file with your custom name and pass the filename
into wandb.init(config="special_config.yaml").
See https://docs.wandb.com/library/config#file-based-configs.

**Examples**:

Basic usage
```
wandb.config.epochs = 4
wandb.init()
for x in range(wandb.config.epochs):
# train
```

Using wandb.init to set config
```
- `wandb.init(config={"epochs"` - 4, "batch_size": 32})
for x in range(wandb.config.epochs):
# train
```

Nested configs
```
wandb.config['train']['epochs] = 4
wandb.init()
for x in range(wandb.config['train']['epochs']):
# train
```

Using absl flags

```
flags.DEFINE_string(‘model’, None, ‘model to run’) # name, default, help
wandb.config.update(flags.FLAGS) # adds all absl flags to config
```

Argparse flags
```
wandb.init()
wandb.config.epochs = 4

parser = argparse.ArgumentParser()
parser.add_argument('-b', '--batch-size', type=int, default=8, metavar='N',
help='input batch size for training (default: 8)')
args = parser.parse_args()
wandb.config.update(args)
```

Using TensorFlow flags (deprecated in tensorflow v2)
```
flags = tf.app.flags
flags.DEFINE_string('data_dir', '/tmp/data')
flags.DEFINE_integer('batch_size', 128, 'Batch size.')
wandb.config.update(flags.FLAGS)  # adds all of the tensorflow flags to config
```

<a name="wandb.sdk.wandb_config.Config.persist"></a>
#### persist

```python
 | persist()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_config.py#L163)

Calls the callback if it's set

<a name="wandb.sdk.wandb_history"></a>
# wandb.sdk.wandb\_history

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_history.py#L3)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_history.py#L23)

Time series data for Runs. This is essentially a list of dicts where each
dict is a set of summary statistics logged.

<a name="wandb.sdk.wandb_init"></a>
# wandb.sdk.wandb\_init

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_init.py#L3)

init.

<a name="wandb.sdk.wandb_init._WandbInit"></a>
## \_WandbInit Objects

```python
class _WandbInit(object)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_init.py#L47)

<a name="wandb.sdk.wandb_init._WandbInit.setup"></a>
#### setup

```python
 | setup(kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_init.py#L59)

Complete setup for wandb.init(). This includes parsing all arguments,
applying them with settings and enabling logging.

<a name="wandb.sdk.wandb_init.init"></a>
#### init

```python
init(job_type: Optional[str] = None, dir=None, config: Union[Dict, str, None] = None, project: Optional[str] = None, entity: Optional[str] = None, reinit: bool = None, tags: Optional[Sequence] = None, group: Optional[str] = None, name: Optional[str] = None, notes: Optional[str] = None, magic: Union[dict, str, bool] = None, config_exclude_keys=None, config_include_keys=None, anonymous: Optional[str] = None, mode: Optional[str] = None, allow_val_change: Optional[bool] = None, resume: Optional[Union[bool, str]] = None, force: Optional[bool] = None, tensorboard=None, sync_tensorboard=None, monitor_gym=None, save_code=None, id=None, settings: Union[Settings, Dict[str, Any], None] = None) -> Union[Run, Dummy]
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_init.py#L447)

Initialize W&B
Spawns a new process to start or resume a run locally and communicate with a
wandb server. Should be called before any calls to wandb.log.

**Arguments**:

- `job_type` _str, optional_ - The type of job running, defaults to 'train'
- `dir` _str, optional_ - An absolute path to a directory where metadata will
be stored.
config (dict, argparse, or absl.flags, str, optional):
Sets the config parameters (typically hyperparameters) to store with the
run. See also wandb.config.
If dict, argparse or absl.flags: will load the key value pairs into
the runs config object.
If str: will look for a yaml file that includes config parameters and
load them into the run's config object.
- `project` _str, optional_ - W&B Project.
- `entity` _str, optional_ - W&B Entity.
- `reinit` _bool, optional_ - Allow multiple calls to init in the same process.
- `tags` _list, optional_ - A list of tags to apply to the run.
- `group` _str, optional_ - A unique string shared by all runs in a given group.
- `name` _str, optional_ - A display name for the run which does not have to be
unique.
- `notes` _str, optional_ - A multiline string associated with the run.
- `magic` _bool, dict, or str, optional_ - magic configuration as bool, dict,
json string, yaml filename.
- `config_exclude_keys` _list, optional_ - string keys to exclude storing in W&B
when specifying config.
- `config_include_keys` _list, optional_ - string keys to include storing in W&B
when specifying config.
- `anonymous` _str, optional_ - Can be "allow", "must", or "never". Controls
whether anonymous logging is allowed.  Defaults to never.
- `mode` _str, optional_ - Can be "online", "offline" or "disabled". Defaults to
online.
- `allow_val_change` _bool, optional_ - allow config values to be changed after
setting. Defaults to true in jupyter and false otherwise.
- `resume` _bool, str, optional_ - Sets the resuming behavior. Should be one of:
"allow", "must", "never", "auto" or None. Defaults to None.
Cases:
- "auto" (or True): automatically resume the previous run on the same machine.
if the previous run crashed, otherwise starts a new run.
- "allow": if id is set with init(id="UNIQUE_ID") or WANDB_RUN_ID="UNIQUE_ID"
and it is identical to a previous run, wandb will automatically resume the
run with the id. Otherwise wandb will start a new run.
- "never": if id is set with init(id="UNIQUE_ID") or WANDB_RUN_ID="UNIQUE_ID"
and it is identical to a previous run, wandb will crash.
- "must": if id is set with init(id="UNIQUE_ID") or WANDB_RUN_ID="UNIQUE_ID"
and it is identical to a previous run, wandb will automatically resume the
run with the id. Otherwise wandb will crash.
- None: never resumes - if a run has a duplicate run_id the previous run is
overwritten.
See https://docs.wandb.com/library/advanced/resuming for more detail.
- `force` _bool, optional_ - If true, will cause script to crash if user can't or isn't
logged in to a wandb server.  If false, will cause script to run in offline
modes if user can't or isn't logged in to a wandb server. Defaults to false.
- `sync_tensorboard` _bool, optional_ - Synchronize wandb logs from tensorboard or
tensorboardX and saves the relevant events file. Defaults to false.
- `monitor_gym` - (bool, optional): automatically logs videos of environment when
using OpenAI Gym (see https://docs.wandb.com/library/integrations/openai-gym)
Defaults to false.
- `save_code` _bool, optional_ - Save the entrypoint or jupyter session history
source code.
- `id` _str, optional_ - A globally unique (per project) identifier for the run. This
is primarily used for resuming.


**Examples**:

Basic usage
```
wandb.init()
```

Launch multiple runs from the same script
```
for x in range(10):
with wandb.init(project="my-projo") as run:
for y in range(100):
- `run.log({"metric"` - x+y})
```


**Raises**:

- `Exception` - if problem.


**Returns**:

A `Run` object.

<a name="wandb.sdk.wandb_login"></a>
# wandb.sdk.wandb\_login

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_login.py#L3)

Log in to Weights & Biases, authenticating your machine to log data to your
account.

<a name="wandb.sdk.wandb_login.login"></a>
#### login

```python
login(anonymous=None, key=None, relogin=None, host=None, force=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_login.py#L22)

Log in to W&B.

**Arguments**:

- `anonymous` _string, optional_ - Can be "must", "allow", or "never".
If set to "must" we'll always login anonymously, if set to
"allow" we'll only create an anonymous user if the user
isn't already logged in.
- `key` _string, optional_ - authentication key.
- `relogin` _bool, optional_ - If true, will re-prompt for API key.
- `host` _string, optional_ - The host to connect to.


**Returns**:

- `bool` - if key is configured


**Raises**:

UsageError - if api_key can not configured and no tty

<a name="wandb.sdk.wandb_run"></a>
# wandb.sdk.wandb\_run

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L3)

The run object corresponds to a single execution of your script,
typically this is an ML experiment. Create a run with wandb.init().

<a name="wandb.sdk.wandb_run.RunStatusChecker"></a>
## RunStatusChecker Objects

```python
class RunStatusChecker(object)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L97)

Periodically polls the background process for relevant updates.

For now, we just use this to figure out if the user has requested a stop.

<a name="wandb.sdk.wandb_run.Run"></a>
## Run Objects

```python
class Run(object)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L136)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L335)

str: The directory where all of the files associated with the run are
placed.

<a name="wandb.sdk.wandb_run.Run.config"></a>
#### config

```python
 | @property
 | config()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L342)

(`Config`): A config object (similar to a nested dict) of key
value pairs associated with the hyperparameters of the run.

<a name="wandb.sdk.wandb_run.Run.name"></a>
#### name

```python
 | @property
 | name()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L353)

str: the display name of the run. It does not need to be unique
and ideally is descriptive.

<a name="wandb.sdk.wandb_run.Run.notes"></a>
#### notes

```python
 | @property
 | notes()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L369)

str: notes associated with the run. Notes can be a multiline string
and can also use markdown and latex equations inside $$ like $\\{x}

<a name="wandb.sdk.wandb_run.Run.tags"></a>
#### tags

```python
 | @property
 | tags() -> Optional[Tuple]
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L385)

Tuple[str]: tags associated with the run

<a name="wandb.sdk.wandb_run.Run.id"></a>
#### id

```python
 | @property
 | id()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L399)

str: the run_id associated with the run

<a name="wandb.sdk.wandb_run.Run.sweep_id"></a>
#### sweep\_id

```python
 | @property
 | sweep_id()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L404)

(str, optional): the sweep id associated with the run or None

<a name="wandb.sdk.wandb_run.Run.path"></a>
#### path

```python
 | @property
 | path()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L411)

str: the path to the run [entity]/[project]/[run_id]

<a name="wandb.sdk.wandb_run.Run.start_time"></a>
#### start\_time

```python
 | @property
 | start_time()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L420)

int: the unix time stamp in seconds when the run started

<a name="wandb.sdk.wandb_run.Run.starting_step"></a>
#### starting\_step

```python
 | @property
 | starting_step()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L428)

int: the first step of the run

<a name="wandb.sdk.wandb_run.Run.resumed"></a>
#### resumed

```python
 | @property
 | resumed()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L436)

bool: whether or not the run was resumed

<a name="wandb.sdk.wandb_run.Run.step"></a>
#### step

```python
 | @property
 | step()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L444)

int: step counter

Every time you call wandb.log() it will by default increment the step
counter.

<a name="wandb.sdk.wandb_run.Run.mode"></a>
#### mode

```python
 | @property
 | mode()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L457)

For compatibility with 0.9.x and earlier, deprecate eventually.

<a name="wandb.sdk.wandb_run.Run.group"></a>
#### group

```python
 | @property
 | group()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L466)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L485)

str: name of W&B project associated with run.

<a name="wandb.sdk.wandb_run.Run.get_url"></a>
#### get\_url

```python
 | get_url()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L489)

Returns: (str, optional): url for the W&B run or None if the run
is offline

<a name="wandb.sdk.wandb_run.Run.get_project_url"></a>
#### get\_project\_url

```python
 | get_project_url()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L497)

Returns: (str, optional): url for the W&B project associated with
the run or None if the run is offline

<a name="wandb.sdk.wandb_run.Run.get_sweep_url"></a>
#### get\_sweep\_url

```python
 | get_sweep_url()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L505)

Returns: (str, optional): url for the sweep associated with the run
or None if there is no associated sweep or the run is offline.

<a name="wandb.sdk.wandb_run.Run.url"></a>
#### url

```python
 | @property
 | url()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L514)

str: name of W&B url associated with run.

<a name="wandb.sdk.wandb_run.Run.entity"></a>
#### entity

```python
 | @property
 | entity()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L519)

str: name of W&B entity associated with run. Entity is either
a user name or an organization name.

<a name="wandb.sdk.wandb_run.Run.log"></a>
#### log

```python
 | log(data, step=None, commit=None, sync=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L673)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L808)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L903)

Marks a run as finished, and finishes uploading all data.  This is
used when creating multiple runs in the same process.  We automatically
call this method when your script exits.

<a name="wandb.sdk.wandb_run.Run.join"></a>
#### join

```python
 | join(exit_code=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L917)

Deprecated alias for finish() - please use finish

<a name="wandb.sdk.wandb_run.Run.plot_table"></a>
#### plot\_table

```python
 | plot_table(vega_spec_name, data_table, fields, string_fields=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L921)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L1553)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L1608)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L1662)

Launch an alert with the given title and text.

**Arguments**:

- `title` _str_ - The title of the alert, must be less than 64 characters long
- `text` _str_ - The text body of the alert
- `level` _str or wandb.AlertLevel, optional_ - The alert level to use, either: "INFO", "WARN", or "ERROR"
- `wait_duration` _int, float, or timedelta, optional_ - The time to wait (in seconds) before sending another alert
with this title

<a name="wandb.sdk.wandb_run.restore"></a>
#### restore

```python
restore(name: str, run_path: Optional[str] = None, replace: bool = False, root: Optional[str] = None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L1708)

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

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_run.py#L1776)

Wrapper for a file object that serializes writes.

<a name="wandb.sdk.wandb_save"></a>
# wandb.sdk.wandb\_save

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_save.py#L2)

save.

<a name="wandb.sdk.wandb_settings"></a>
# wandb.sdk.wandb\_settings

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_settings.py#L2)

Settings.

This module configures settings which impact wandb runs.

Order of loading settings: (differs from priority)
defaults
environment
wandb.setup(settings=)
system_config
workspace_config
wandb.init(settings=)
network_org
network_entity
network_project

Priority of settings:  See "source" variable.

When override is used, it has priority over non-override settings

Override priorities are in the reverse order of non-override settings

<a name="wandb.sdk.wandb_settings.Settings"></a>
## Settings Objects

```python
class Settings(object)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_settings.py#L188)

Settings Constructor

**Arguments**:

- `entity` - personal user or team to use for Run.
- `project` - project name for the Run.


**Raises**:

- `Exception` - if problem.

<a name="wandb.sdk.wandb_settings.Settings.__copy__"></a>
#### \_\_copy\_\_

```python
 | __copy__()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_settings.py#L657)

Copy (note that the copied object will not be frozen).

<a name="wandb.sdk.wandb_summary"></a>
# wandb.sdk.wandb\_summary

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_summary.py#L2)

<a name="wandb.sdk.wandb_summary.SummaryDict"></a>
## SummaryDict Objects

```python
@six.add_metaclass(abc.ABCMeta)
class SummaryDict(object)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_summary.py#L18)

dict-like which wraps all nested dictionraries in a SummarySubDict,
and triggers self._root._callback on property changes.

<a name="wandb.sdk.wandb_summary.Summary"></a>
## Summary Objects

```python
class Summary(SummaryDict)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_summary.py#L78)

Summary

The summary statistics are used to track single metrics per model. Calling
wandb.log({'accuracy': 0.9}) will automatically set wandb.summary['accuracy']
to be 0.9 unless the code has changed wandb.summary['accuracy'] manually.

Setting wandb.summary['accuracy'] manually can be useful if you want to keep
a record of the accuracy of the best model while using wandb.log() to keep a
record of the accuracy at every step.

You may want to store evaluation metrics in a runs summary after training has
completed. Summary can handle numpy arrays, pytorch tensors or tensorflow tensors.
When a value is one of these types we persist the entire tensor in a binary file
and store high level metrics in the summary object such as min, mean, variance,
95% percentile, etc.

**Examples**:

```
wandb.init(config=args)

best_accuracy = 0
for epoch in range(1, args.epochs + 1):
test_loss, test_accuracy = test()
if (test_accuracy > best_accuracy):
wandb.run.summary["best_accuracy"] = test_accuracy
best_accuracy = test_accuracy
```

<a name="wandb.sdk.wandb_summary.SummarySubDict"></a>
## SummarySubDict Objects

```python
class SummarySubDict(SummaryDict)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_summary.py#L128)

Non-root node of the summary data structure. Contains a path to itself
from the root.

<a name="wandb.sdk.wandb_watch"></a>
# wandb.sdk.wandb\_watch

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_watch.py#L2)

watch.

<a name="wandb.sdk.wandb_watch.watch"></a>
#### watch

```python
watch(models, criterion=None, log="gradients", log_freq=1000, idx=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_watch.py#L17)

Hooks into the torch model to collect gradients and the topology.  Should be extended
to accept arbitrary ML models.

**Arguments**:

- `models` _torch.Module_ - The model to hook, can be a tuple
- `criterion` _torch.F_ - An optional loss value being optimized
- `log` _str_ - One of "gradients", "parameters", "all", or None
- `log_freq` _int_ - log gradients and parameters every N batches
- `idx` _int_ - an index to be used when calling wandb.watch on multiple models


**Returns**:

`wandb.Graph` The graph object that will populate after the first backward pass

<a name="wandb.sdk.wandb_watch.unwatch"></a>
#### unwatch

```python
unwatch(models=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_watch.py#L82)

Remove pytorch gradient and parameter hooks.

**Arguments**:

- `models` _list_ - Optional list of pytorch models that have had watch called on them

