---
title: Config
---

<a name="wandb.sdk.wandb_config"></a>
# wandb.sdk.wandb\_config

[[view_source]](https://github.com/wandb/client/blob/88104ce0f95c9cf58676b249510db7ba56efda09/wandb/sdk/wandb_config.py#L3)

Config is a dictionary-like object useful for tracking inputs to your script,
like hyperparameters. We suggest you set this once at the beginning of your job,
when you initialize the run like so: wandb.init(config={"key": "value"}).
For example, if you're training an ML model, you might track learning_rate and
batch_size in config.

<a name="wandb.sdk.wandb_config.Config"></a>
## Config Objects

```python
class Config(object)
```

[[view_source]](https://github.com/wandb/client/blob/88104ce0f95c9cf58676b249510db7ba56efda09/wandb/sdk/wandb_config.py#L32)

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

[[view_source]](https://github.com/wandb/client/blob/88104ce0f95c9cf58676b249510db7ba56efda09/wandb/sdk/wandb_config.py#L167)

Calls the callback if it's set

