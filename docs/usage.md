# Usage

## CLI

Initialize the current directory with a project

```console
$ wandb init
```

Describe the next run using Markdown

```console
$ wandb describe
```

Checkout the commit associated with the bucket and restore the config variables

```console
$ wandb restore
```

Pull the current project from the cloud

```console
$ wandb pull some-bucket
```

Push the current project to the cloud

```console
$ wandb push some-bucket model.json weights.h5
```

Manually login to Weights & Biases

```console
$ wandb login
```

Sync the stdout of the training process and the current project to the cloud

```console
$ ./train.sh arg1 arg2 | wandb some-bucket model.json weights.h5
```

Add files to be tracked in this directory to avoid needing to specify them in the above commands.

```console
$ wandb add model.json weights.h5
```

Get the status of the files in the current project

```console
$ wandb status
```

List the buckets in your project

```console
$ wandb buckets
```

List the projects in your account

```console
$ wandb projects
```

### Config commands

W&B configuration makes tracking exactly what configuration parameters were used in a 
given training automatic.  You can benefit from W&B configuration tracking by changing a single line
of your training script.  If you decide to read configuration from our configuration object
we store defaults in a YAML file at the root of your project.  The configuration object
automatically looks for overrides in the environment (if `WANDB_` is prepended to the name) as
well as in command line flags.

Initialize a directory for configuration.  This creates a file named `config.yaml` in the current directory.

```console
$ wandb config init
```

Set configuration variables

```console
$ wandb config set batch_size=25
$ wandb config set batch_size=25 -d "The size of a mini-batch"
$ wandb config set batch_size=25 epochs=10
```

Import configuration from existing code.  If you're currently just setting parameters with optional comments in python, this is a great way to get started organizing parameters.

```console
$ wandb config import
```

Pasting the following into the editor will set the appropriate values in the config.

```python
# The size of a mini-batch
batch_size=25
epochs = 10
```

Remove a configuration variable

```console
$ wandb config rm batch_size
```

Show the current configuration

```console
$ wandb config show
$ wandb config show -f json
```

## Python Module

Setup the configuration and optionally a client.  As long as you've run `wandb init` in the current directory there's no need to provide credentials or a project name.

```python
import wandb
conf = wandb.Config()
wandb.sync(files=["*.h5"])
```

Set or use configuration parameters.  This enables W&B to keep track of all configuration parameters for a given training run.

```python
conf.some_rate = 1.5
if conf.some_rate < 1:
    pass
```

If your training code already uses something like `argparse` or `tensorflow.flags` you can pass the parsed object to get tracking for free.

```python
args = parser.parse_known_args()
conf = wandb.Config(args)
conf = wandb.Config(FLAGS)
```

The next time you push a bucket, the configuration parameters will be synced to W&B.

Pull the bucket specified from the cloud.  The default project will be overridden if a "/" is in the bucket name.

```python
wandb.pull("cool/stuff")
```

Push the current project to the cloud.  File paths are relative to the current working directory.

```python
wandb.push("some-bucket", files=["model.json", "weights.h5"])
```