# Usage

## CLI

Initialize the current directory with a project

```console
$ wandb init
```

Manually login to Weights & Biases

```console
$ wandb login
```

Pull the current project from the cloud

```console
$ wandb pull some-bucket
```

Push the current project to the cloud

```console
$ wandb push some-bucket model.json weights.h5
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


## Python Module

Setup the client.  As long as you've run `wandb init` in the current directory there's no need to provide credentials or a project name.

```python
import wandb
client = wandb.API()
```

Pull the bucket specified from the cloud.  The default project will be overridden if a "/" is in the bucket name.

```python
client.pull("zoo/vgg-16")
```

Push the current project to the cloud.  File paths are relative to the current working directory.

```python
client.push("some-bucket", files=["model.json", "weights.h5"])
```