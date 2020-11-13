---
title: Config
---

<a name="wandb.sdk.wandb_config"></a>
# wandb.sdk.wandb\_config

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_config.py#L3)

config.

<a name="wandb.sdk.wandb_config.Config"></a>
## Config Objects

```python
class Config(object)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_config.py#L28)

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

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_config.py#L163)

Calls the callback if it's set

<a name="wandb.sdk.wandb_run"></a>
# wandb.sdk.wandb\_run

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_run.py#L4)

<a name="wandb.sdk.wandb_run.Run"></a>
## Run Objects

```python
class Run(object)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_run.py#L132)

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

<a name="wandb.sdk.wandb_run.Run.config"></a>
#### config

```python
 | @property
 | config()
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_run.py#L341)

(`Config`): A config object (similar to a nested dict) of key
value pairs associated with the hyperparameters of the run.

