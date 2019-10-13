# Catalyst

Sergey Kolesnikov, creator of [Catalyst](https://github.com/catalyst-team/catalyst), has built an awesome W&B integration. If you are using Catalyst, we have a runner that can automatically log all hyperparameters, metrics, TensorBoard, the best trained model, and all `stdout` during training.

```text
import torch
from catalyst.dl import SupervisedWandbRunner

# experiment setup
logdir = "./logdir"
num_epochs = 42

# data
loaders = {"train": ..., "valid": ...}

# model, criterion, optimizer
model = Net()
criterion = torch.nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters())
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer)

# model runner
runner = SupervisedWandbRunner()

# model training
runner.train(
    model=model,
    criterion=criterion,
    optimizer=optimizer,
    scheduler=scheduler,
    loaders=loaders,
    logdir=logdir,
    num_epochs=num_epochs,
    verbose=True
)
```

Custom parameters can also be given at that stage.

```text
# model training
runner.train(
    model=model,
    criterion=criterion,
    optimizer=optimizer,
    scheduler=scheduler,
    loaders=loaders,
    logdir=logdir,
    num_epochs=num_epochs,
    verbose=True,
    monitoring_params={
        "project": "my-research-project",
        "group": "finetuning"
    }
)
```

Check out our [classification tutorial](https://github.com/catalyst-team/catalyst/blob/master/examples/notebooks/classification-tutorial-wandb.ipynb)[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/catalyst-team/catalyst/blob/master/examples/notebooks/classification-tutorial-wandb.ipynb)for complete example code.

#### Options

`monitoring_params` supports a number of options:

| Keyword argument | Default | Description |
| :--- | :--- | :--- |
| job\_type | None | The type of job running, defaults to 'train' |
| config | None | The hyper parameters to store with the run |
| project | None | The project to push metrics to |
| entity | None | The entity to push metrics to |
| dir | None | An absolute path to a directory where metadata will be stored |
| group | None | A unique string shared by all runs in a given group |
| tags | None | A list of tags to apply to the run |
| id | None | A globally unique \(per project\) identifier for the run |
| name | None | A display name which does not have to be unique |
| notes | None | A multiline string associated with the run |
| reinit | None | Allow multiple calls to init in the same process |
| resume | False | Automatically resume this run if run from the same machine, you can also pass a unique run\_id |
| sync\_tensorboard | False | Synchronize wandb logs to TensorBoard or TensorboardX |
| force | False | Force authentication with wandb |

