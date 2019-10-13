# Fast.ai

For scripts using fast.ai, we have a callback that can automatically log model topology, losses, metrics, weights, gradients, sample predictions and best trained model.

```text
import wandb
from wandb.fastai import WandbCallback

wandb.init()

learn = cnn_learner(data,
                    model,
                    callback_fns=WandbCallback)
learn.fit(epochs)
```

Requested logged data is configurable through the callback constructor.

```text
from functools import partial

learn = cnn_learner(data, model, callback_fns=partial(WandbCallback, input_type='images'))
```

It is also possible to use WandbCallback only when starting training. In this case it must be instantiated.

```text
learn.fit(epochs, callbacks=WandbCallback(learn))
```

Custom parameters can also be given at that stage.

```text
learn.fit(epochs, callbacks=WandbCallback(learn, input_type='images'))
```

#### Example Code

Check out our [Example GitHub Repo](https://github.com/wandb/examples) for complete example code.

#### Options

`WandbCallback()` class supports a number of options:

| Keyword argument | Default | Description |
| :--- | :--- | :--- |
| learn | N/A | the fast.ai learner to hook. |
| save\_model | True | save the model if it's improved at each step. It will also load best model at the end of training. |
| mode | auto | 'min', 'max', or 'auto': How to compare the training metric specified in `monitor` between steps. |
| monitor | None | training metric used to measure performance for saving the best model. None defaults to validation loss. |
| log | gradients | "gradients", "parameters", "all", or None. Losses & metrics are always logged. |
| input\_type | None | "images" or None. Used to display sample predictions. |
| validation\_data | None | data used for sample predictions if input\_type is set. |
| predictions | 36 | number of predictions to make if input\_type is set and validation\_data is None. |
| seed | 12345 | initialize random generator for sample predictions if input\_type is set and validation\_data is None. |

