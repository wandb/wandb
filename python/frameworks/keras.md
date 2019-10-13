---
description: How to integrate a Keras script to log metrics to W&B
---

# Keras

Use the Keras callback to automatically save all the metrics and the loss values tracked in `model.fit`.

{% code-tabs %}
{% code-tabs-item title="example.py" %}
```python
import wandb
from wandb.keras import WandbCallback
wandb.init(config={"hyper": "parameter"})

# Magic

model.fit(X_train, y_train,  validation_data=(X_test, y_test),
          callbacks=[WandbCallback()])

```
{% endcode-tabs-item %}
{% endcode-tabs %}

See our [example projects](../example-projects/) for a complete script example.

#### Options

Keras `WandbCallback()` class supports a number of options:

| Keyword argument | Default | Description |
| :--- | :--- | :--- |
| monitor | val\_loss | The training metric used to measure performance for saving the best model. i.e. val\_loss |
| mode | auto | 'min', 'max', or 'auto': How to compare the training metric specified in `monitor` between steps |
| save\_weights\_only | False | only save the weights instead of the entire model |
| save\_model | True | save the model if it's improved at each step |
| log\_weights | False | log the values of each layers parameters at each epoch |
| log\_gradients | False | log the gradients of each layers parametres at each epcoh |
| training\_data | None | tuple \(X,y\) needed for calculating gradients |
| data\_type | None | the type of data we're saving, currently only "image" is supported |
| labels | None | only used if data\_type is specified, list of labels to convert numeric output to if you are building classifier. \(supports binary classification\) |
| predictions | 36 | the number of predictions to make if data\_type is specified. Max is 100. |
| generator | None | if using data augmentation and data\_type you can specify a generator to make predictions with. |

