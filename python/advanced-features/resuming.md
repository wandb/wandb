# Resuming

You can have wandb automatically resume runs by passing `resume=True` to `wandb.init()`. If your process doesn't exit successfully, the next time you run it wandb will start logging from the last step. Below is a simple example in Keras:

```python
import keras
import numpy as np
import wandb
from wandb.keras import WandbCallback
wandb.init(project="preemptable", resume=True)

if wandb.run.resumed:
    # restore the best model
    model = keras.models.load_model(wandb.restore("model-best.h5").name)
else:
    a = keras.layers.Input(shape=(32,))
    b = keras.layers.Dense(10)(a)
    model = keras.models.Model(input=a,output=b)

model.compile("adam", loss="mse")
model.fit(np.random.rand(100, 32), np.random.rand(100, 10),
    # set the resumed epoch
    initial_epoch=wandb.run.step, epochs=300,
    # save the best model if it improved each epoch
    callbacks=[WandbCallback(save_model=True, monitor="loss")])
```

Automatic resuming only works if the process is restarted on top of the same filesystem as the failed process. If you can't share a filesystem, we allow you to set a globally unique string \(per project\) corresponding to a single run of your script. It must be no longer than 64 characters. All non-word characters will be converted to dashes.

If you set **WANDB\_RESUME** equal to "allow" you can always set **WANDB\_RUN\_ID** to a unique string and restarts of the process will automatically be handled. You can also pass a unique string when calling init i.e. `wandb.init(resume="run-32")`. If you set **WANDB\_RESUME** equal to "must", wandb will throw an error if a run does not exist instead of auto-creating.

| Method | Syntax | Never Resume \(default\) | Always Resume | Resume specifying run id | Resume from same directory |
| :--- | :--- | :--- | :--- | :--- | :--- |
| command line | wandb run --resume= | "never" | "must" | "allow" \(Requires WANDB\_RUN\_ID=RUN\_ID\) | \(not available\) |
| environment | WANDB\_RESUME= | "never" | "must" | "allow" \(Requires WANDB\_RUN\_ID=RUN\_ID\) | \(not available\) |
| init | wandb.init\(resume=\) |  | \(not available\) | resume=RUN\_ID | resume=True |

{% hint style="warning" %}
If multiple processes use the same run\_id concurrently unexpected results will be recorded and rate limiting will occur.
{% endhint %}

