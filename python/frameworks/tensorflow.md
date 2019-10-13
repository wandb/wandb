---
description: How to integrate a TensorFlow script to log metrics to W&B
---

# TensorFlow

If you're already using TensorBoard, it's easy to integrate with wandb.

```text
import tensorflow as tf
import wandb
wandb.init(config=tf.flags.FLAGS, sync_tensorboard=True)
```

See our [example projects](../example-projects/) for a complete script example.

### Custom Metrics

If you need to log additional custom metrics that aren't being logged to TensorBoard, you can call `wandb.log` in your code with the same step argument that TensorBoard is using: ie. `wandb.log({"custom": 0.8}, step=global_step)`

### TensorFlow Hook

If you want more control over what get's logged, wandb also provides a hook for TensorFlow estimators. It will log all `tf.summary` values in the graph.

```text
import tensorflow as tf
import wandb

wandb.init(config=tf.FLAGS)

estimator.train(hooks=[wandb.tensorflow.WandbHook(steps_per_log=1000)])
```

### Manual Logging

The simplest way to log metrics in TensorFlow is by logging `tf.summary` with the TensorFlow logger:

```text
import wandb

with tf.Session() as sess:
    # ...
    wandb.tensorflow.log(tf.summary.merge_all())
```

