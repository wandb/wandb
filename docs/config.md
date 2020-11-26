---
title: Config
---

<a name="wandb.sdk.wandb_config"></a>
# wandb.sdk.wandb\_config

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/sdk/wandb_config.py#L3)

Config is a dictionary-like object useful for tracking inputs to your script,
like hyperparameters. We suggest you set this once at the beginning of your job,
when you initialize the run like so: `wandb.init(config={"key": "value"})`.
For example, if you're training an ML model, you might track learning_rate and
batch_size in config.

<a name="wandb.sdk.wandb_config.Config"></a>
## Config Objects

```python
class Config(object)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/sdk/wandb_config.py#L32)

Use the config object to save your run's hyperparameters. When you call
wandb.init() to start a new tracked run, a run object is saved. We recommend
saving the config object with the run at the same time, like so:
`wandb.init(config=my_config_dict)`.

You can create a file called config-defaults.yaml, and wandb will auto-load
your config into wandb.config. Alternatively, you can use a YAML file with a
custom name and pass the filename: `wandb.init(config="my_config_file.yaml")`
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

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/sdk/wandb_config.py#L162)

Calls the callback if it's set

