---
title: Init
---

<a name="wandb.sdk.wandb_init"></a>
# wandb.sdk.wandb\_init

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_init.py#L3)

wandb.init() indicates the beginning of a new run. In an ML training pipeline,
you could add wandb.init() to the beginning of your training script as well as
your evaluation script, and each piece steps would be tracked as a run in W&B.

<a name="wandb.sdk.wandb_init._WandbInit"></a>
## \_WandbInit Objects

```python
class _WandbInit(object)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_init.py#L50)

<a name="wandb.sdk.wandb_init._WandbInit.setup"></a>
#### setup

```python
 | setup(kwargs)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_init.py#L62)

Complete setup for wandb.init(). This includes parsing all arguments,
applying them with settings and enabling logging.

<a name="wandb.sdk.wandb_init.init"></a>
#### init

```python
init(job_type: Optional[str] = None, dir=None, config: Union[Dict, str, None] = None, project: Optional[str] = None, entity: Optional[str] = None, reinit: bool = None, tags: Optional[Sequence] = None, group: Optional[str] = None, name: Optional[str] = None, notes: Optional[str] = None, magic: Union[dict, str, bool] = None, config_exclude_keys=None, config_include_keys=None, anonymous: Optional[str] = None, mode: Optional[str] = None, allow_val_change: Optional[bool] = None, resume: Optional[Union[bool, str]] = None, force: Optional[bool] = None, tensorboard=None, sync_tensorboard=None, monitor_gym=None, save_code=None, id=None, settings: Union[Settings, Dict[str, Any], None] = None) -> Union[Run, Dummy]
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_init.py#L456)

Initialize W&B
Spawns a new process to start or resume a run locally and communicate with a
wandb server. Should be called before any calls to wandb.log.

**Arguments**:

- `project` _str, optional_ - The name of the project where you're sending
the new run. If the project is not specified, the run is put in an
"Uncategorized" project.
- `entity` _str, optional_ - An entity is a username or team name where
you're sending runs. This entity must exist before you can send runs
there, so make sure to create your account or team in the UI before
starting to log runs.
If you don't specify an entity, the run will be sent to your default
entity, which is usually your username. Change your default entity
in [Settings](wandb.ai/settings) under "default location to create
new projects".
config (dict, argparse, absl.flags, str, optional):
This sets wandb.config, a dictionary-like object for saving inputs
to your job, like hyperparameters for a model or settings for a data
preprocessing job. The config will show up in a table in the UI that
you can use to group, filter, and sort runs. Keys should not contain
`.` in their names, and values should be under 10 MB.
If dict, argparse or absl.flags: will load the key value pairs into
the wandb.config object.
If str: will look for a yaml file by that name, and load config from
that file into the wandb.config object.
- `save_code` _bool, optional_ - Turn this on to save the main script or
notebook to W&B. This is valuable for improving experiment
reproducibility and to diff code across experiments in the UI. By
default this is off, but you can flip the default behavior to "on"
in [Settings](wandb.ai/settings).
- `group` _str, optional_ - Specify a group to organize individual runs into
a larger experiment. For example, you might be doing cross
validation, or you might have multiple jobs that train and evaluate
a model against different test sets. Group gives you a way to
organize runs together into a larger whole, and you can toggle this
on and off in the UI. For more details, see
[Grouping](docs.wandb.com/library/grouping).
- `job_type` _str, optional_ - Specify the type of run, which is useful when
you're grouping runs together into larger experiments using group.
For example, you might have multiple jobs in a group, with job types
like train and eval. Setting this makes it easy to filter and group
similar runs together in the UI so you can compare apples to apples.
- `tags` _list, optional_ - A list of strings, which will populate the list
of tags on this run in the UI. Tags are useful for organizing runs
together, or applying temporary labels like "baseline" or
"production". It's easy to add and remove tags in the UI, or filter
down to just runs with a specific tag.
- `name` _str, optional_ - A short display name for this run, which is how
you'll identify this run in the UI. By default we generate a random
two-word name that lets you easily cross-reference runs from the
table to charts. Keeping these run names short makes the chart
legends and tables easier to read. If you're looking for a place to
save your hyperparameters, we recommend saving those in config.
- `notes` _str, optional_ - A longer description of the run, like a -m commit
message in git. This helps you remember what you were doing when you
ran this run.
- `dir` _str, optional_ - An absolute path to a directory where metadata will
be stored. When you call download() on an artifact, this is the
directory where downloaded files will be saved. By default this is
the ./wandb directory.
- `sync_tensorboard` _bool, optional_ - Whether to copy all TensorBoard logs
to W&B (default: False).
[Tensorboard](https://docs.wandb.com/integrations/tensorboard)
- `resume` _bool, str, optional_ - Sets the resuming behavior. Options:
"allow", "must", "never", "auto" or None. Defaults to None.
Cases:
- None (default): If the new run has the same ID as a previous run,
this run overwrites that data.
- "auto" (or True): if the preivous run on this machine crashed,
automatically resume it. Otherwise, start a new run.
- "allow": if id is set with init(id="UNIQUE_ID") or
WANDB_RUN_ID="UNIQUE_ID" and it is identical to a previous run,
wandb will automatically resume the run with that id. Otherwise,
wandb will start a new run.
- "never": if id is set with init(id="UNIQUE_ID") or
WANDB_RUN_ID="UNIQUE_ID" and it is identical to a previous run,
wandb will crash.
- "must": if id is set with init(id="UNIQUE_ID") or
WANDB_RUN_ID="UNIQUE_ID" and it is identical to a previous run,
wandb will automatically resume the run with the id. Otherwise
wandb will crash.
See https://docs.wandb.com/library/advanced/resuming for more.
- `reinit` _bool, optional_ - Allow multiple wandb.init() calls in the same
process. (default: False)

- `magic` _bool, dict, or str, optional_ - magic configuration as bool, dict,
json string, yaml filename.
- `config_exclude_keys` _list, optional_ - string keys to exclude from
wandb.config.
- `config_include_keys` _list, optional_ - string keys to include in
wandb.config.
- `anonymous` _str, optional_ - Can be "allow", "must", or "never". Controls
whether anonymous logging is allowed.  Defaults to never.
- `mode` _str, optional_ - Can be "online", "offline" or "disabled". Defaults to
online.
- `allow_val_change` _bool, optional_ - allow config values to be changed after
setting. Defaults to true in jupyter and false otherwise.
- `force` _bool, optional_ - If true, will cause script to crash if user can't or isn't
logged in to a wandb server.  If false, will cause script to run in offline
modes if user can't or isn't logged in to a wandb server. Defaults to false.
- `sync_tensorboard` _bool, optional_ - Synchronize wandb logs from tensorboard or
tensorboardX and saves the relevant events file. Defaults to false.
- `monitor_gym` - (bool, optional): automatically logs videos of environment when
using OpenAI Gym (see https://docs.wandb.com/library/integrations/openai-gym)
Defaults to false.
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

