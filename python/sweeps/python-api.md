---
description: Run sweeps from Jupyter notebooks
---

# Jupyter & Python API

### Initialize a sweep

```python
import wandb

sweep_config = {
  "name": "My Sweep",
  "method": "grid",
  "parameters": {
        "parameter1": {
            "values": [1, 2, 3]
        }
    }
}

sweep_id = wandb.sweep(sweep_config)
```

### Run an agent

When running an agent from python, the agent runs a specified function instead of using the `program` key from the sweep configuration file.

```python
import wandb
import time

def train():
    wandb.init()
    print ("config:", dict(wandb.config.user_items()))
    parameter1 = wandb.config.get("parameter1", 0)
    for x in range(35):
        print("running", x)
        wandb.log({"dog": parameter1, "cat": x})
        time.sleep(1)

wandb.agent(sweep_id, function=train)
```

Example: [Run in colab](https://colab.research.google.com/github/wandb/examples/blob/master/sweeps-python/notebook.ipynb)

### Run a local controller

If you want to develop your own parameter search algorithms you can run your controller from python.

The simplest way to run a controller:

```python
sweep = wandb.controller(sweep_id)
sweep.run()
```

If you want more control of the controller loop:

```python
import wandb
sweep = wandb.controller(sweep_id)
while not sweep.done():
    sweep.print_status()
    sweep.step()
    time.sleep(5)
```

Or even more control over the parameters being served:

```python
import wandb
sweep = wandb.controller(sweep_id)
while not sweep.done():
    params = sweep.search()
    sweep.schedule(params)
    sweep.print_status()
```

If you want to specify your sweep entirely with code you can do something like this:

```python
import wandb
from wandb.sweeps import GridSearch,RandomSearch,BayesianSearch
from wandb.sweeps import HyperbandEarlyTerminate
from wandb.sweeps import EnvelopeEarlyTerminate

sweep = wandb.controller()
sweep.configure_search(GridSearch)
sweep.configure_program('train-dummy.py')
sweep.configure_stopping(EnvelopeEarlyTerminate)
sweep.configure_controller(type="local")
sweep.configure_parameter('param1', value=3)
sweep.create()
sweep.run()
```

