---
title: Config
---

<a name="wandb.sdk.wandb_config"></a>
# wandb.sdk.wandb\_config

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L3)

config.

<a name="wandb.sdk.wandb_config.logger"></a>
#### logger

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L22)

<a name="wandb.sdk.wandb_config.Config"></a>
## Config Objects

```python
class Config(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L28)

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

<a name="wandb.sdk.wandb_config.Config.__init__"></a>
#### \_\_init\_\_

```python
 | __init__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L96)

<a name="wandb.sdk.wandb_config.Config.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L113)

<a name="wandb.sdk.wandb_config.Config.keys"></a>
#### keys

```python
 | keys()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L116)

<a name="wandb.sdk.wandb_config.Config.as_dict"></a>
#### as\_dict

```python
 | as_dict()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L122)

<a name="wandb.sdk.wandb_config.Config.__getitem__"></a>
#### \_\_getitem\_\_

```python
 | __getitem__(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L126)

<a name="wandb.sdk.wandb_config.Config.__setitem__"></a>
#### \_\_setitem\_\_

```python
 | __setitem__(key, val)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L129)

<a name="wandb.sdk.wandb_config.Config.items"></a>
#### items

```python
 | items()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L139)

<a name="wandb.sdk.wandb_config.Config.__setattr__"></a>
#### \_\_setattr\_\_

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L142)

<a name="wandb.sdk.wandb_config.Config.__getattr__"></a>
#### \_\_getattr\_\_

```python
 | __getattr__(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L144)

<a name="wandb.sdk.wandb_config.Config.__contains__"></a>
#### \_\_contains\_\_

```python
 | __contains__(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L147)

<a name="wandb.sdk.wandb_config.Config.update"></a>
#### update

```python
 | update(d, allow_val_change=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L155)

<a name="wandb.sdk.wandb_config.Config.get"></a>
#### get

```python
 | get(*args)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L160)

<a name="wandb.sdk.wandb_config.Config.persist"></a>
#### persist

```python
 | persist()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L163)

Calls the callback if it's set

<a name="wandb.sdk.wandb_config.Config.setdefaults"></a>
#### setdefaults

```python
 | setdefaults(d)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L168)

<a name="wandb.sdk.wandb_config.Config.update_locked"></a>
#### update\_locked

```python
 | update_locked(d, user=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L176)

<a name="wandb.sdk.wandb_config.ConfigStatic"></a>
## ConfigStatic Objects

```python
class ConfigStatic(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L246)

<a name="wandb.sdk.wandb_config.ConfigStatic.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(config)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L247)

<a name="wandb.sdk.wandb_config.ConfigStatic.__setattr__"></a>
#### \_\_setattr\_\_

```python
 | __setattr__(name, value)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L250)

<a name="wandb.sdk.wandb_config.ConfigStatic.__setitem__"></a>
#### \_\_setitem\_\_

```python
 | __setitem__(key, val)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L253)

<a name="wandb.sdk.wandb_config.ConfigStatic.keys"></a>
#### keys

```python
 | keys()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L256)

<a name="wandb.sdk.wandb_config.ConfigStatic.__getitem__"></a>
#### \_\_getitem\_\_

```python
 | __getitem__(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L259)

<a name="wandb.sdk.wandb_config.ConfigStatic.__str__"></a>
#### \_\_str\_\_

```python
 | __str__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_config.py#L262)

