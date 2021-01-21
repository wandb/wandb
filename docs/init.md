---
title: Init
---

<a name="wandb.sdk.wandb_init"></a>
# wandb.sdk.wandb\_init

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L3)

wandb.init() indicates the beginning of a new run. In an ML training pipeline,
you could add wandb.init() to the beginning of your training script as well as
your evaluation script, and each piece steps would be tracked as a run in W&B.

<a name="wandb.sdk.wandb_init.logger"></a>
#### logger

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L36)

<a name="wandb.sdk.wandb_init.online_status"></a>
#### online\_status

```python
online_status(*args, **kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L45)

<a name="wandb.sdk.wandb_init._WandbInit"></a>
## \_WandbInit Objects

```python
class _WandbInit(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L49)

<a name="wandb.sdk.wandb_init._WandbInit.__init__"></a>
#### \_\_init\_\_

```python
 | __init__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L50)

<a name="wandb.sdk.wandb_init._WandbInit.setup"></a>
#### setup

```python
 | setup(kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L61)

Complete setup for wandb.init(). This includes parsing all arguments,
applying them with settings and enabling logging.

<a name="wandb.sdk.wandb_init._WandbInit.teardown"></a>
#### teardown

```python
 | teardown()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L159)

<a name="wandb.sdk.wandb_init._WandbInit.init"></a>
#### init

```python
 | init()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L305)

<a name="wandb.sdk.wandb_init.getcaller"></a>
#### getcaller

```python
getcaller()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L442)

<a name="wandb.sdk.wandb_init.init"></a>
#### init

```python
init(job_type: Optional[str] = None, dir=None, config: Union[Dict, str, None] = None, project: Optional[str] = None, entity: Optional[str] = None, reinit: bool = None, tags: Optional[Sequence] = None, group: Optional[str] = None, name: Optional[str] = None, notes: Optional[str] = None, magic: Union[dict, str, bool] = None, config_exclude_keys=None, config_include_keys=None, anonymous: Optional[str] = None, mode: Optional[str] = None, allow_val_change: Optional[bool] = None, resume: Optional[Union[bool, str]] = None, force: Optional[bool] = None, tensorboard=None, sync_tensorboard=None, monitor_gym=None, save_code=None, id=None, settings: Union[Settings, Dict[str, Any], None] = None) -> Union[Run, Dummy]
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_init.py#L449)

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

