# Config
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_config.py#L28-L243)

`Config`

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










**Example**

Basic usage
```
wandb.config.epochs = 4
wandb.init()
for x in range(wandb.config.epochs):
    # train
```

Using wandb.init to set config
```
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


## Config.persist
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_config.py#L163-L166)

`def persist(self):`

Calls the callback if it's set











## Config._sanitize_val
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_config.py#L222-L243)

`def _sanitize_val(self, val):`

Turn all non-builtin values into something safe for YAML











