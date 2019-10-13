# wandb.config

### Overview

Use `wandb.config` to save hyperparameters and other training inputs. This is useful for comparing runs and reproducing your work. You can use config to save anything that you know about the setup for the run— things like the name of your dataset, the type of model. 

You'll be able to group by config values in the web interface, comparing the settings of different runs and seeing how they affected the out

### Simple Example

```text
wandb.config.epochs = 4   # config variable named epochs is saved with the model
wandb.config.batch_size = 32
```

### Batch Inititialization

You can initialize configs in batches

```text
wandb.init(config={"epochs": 4, "batch_size": 32})
# or
wandb.config.update({"epochs": 4, "batch_size": 32})
```

### TensorFlow Flags

You can pass TensorFlow flags into the config object.

```text
wandb.init()
wandb.config.epochs = 4  # config variables are saved to the cloud

flags = tf.app.flags
flags.DEFINE_string('data_dir', '/tmp/data')
flags.DEFINE_integer('batch_size', 128, 'Batch size.')
wandb.config.update(flags.FLAGS)  # adds all of the tensorflow flags as config variables
```

### Argparse Flags

You can pass in an argparse

```text
wandb.init()
wandb.config.epochs = 4  # config variables are saved to the cloud

parser = argparse.ArgumentParser()
parser.add_argument('--batch-size', type=int, default=8, metavar='N',
                     help='input batch size for training (default: 8)')
args = parser.parse_args()
wandb.config.update(args) # adds all of the arguments as config variables
```

### File-Based Configs

You can create a file called _config-defaults.yaml_ and it will automatically be loaded into the config variable.

```text
# sample config-defaults file
epochs:
  desc: Number of epochs to train over
  value: 100
batch_size:
  desc: Size of each mini-batch
  value: 32
```

You can tell wandb to load different config files with the command line argument `--configs special-configs.yaml` which will load parameters from the file special-configs.yaml.

