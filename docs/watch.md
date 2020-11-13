---
title: Watch
---

<a name="wandb.sdk.wandb_watch"></a>
# wandb.sdk.wandb\_watch

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_watch.py#L2)

watch.

<a name="wandb.sdk.wandb_watch.watch"></a>
#### watch

```python
watch(models, criterion=None, log="gradients", log_freq=1000, idx=None)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_watch.py#L17)

Hooks into the torch model to collect gradients and the topology.  Should be extended
to accept arbitrary ML models.

**Arguments**:

- `models` _torch.Module_ - The model to hook, can be a tuple
- `criterion` _torch.F_ - An optional loss value being optimized
- `log` _str_ - One of "gradients", "parameters", "all", or None
- `log_freq` _int_ - log gradients and parameters every N batches
- `idx` _int_ - an index to be used when calling wandb.watch on multiple models


**Returns**:

`wandb.Graph` The graph object that will populate after the first backward pass

<a name="wandb.sdk.wandb_watch.unwatch"></a>
#### unwatch

```python
unwatch(models=None)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_watch.py#L82)

Remove pytorch gradient and parameter hooks.

**Arguments**:

- `models` _list_ - Optional list of pytorch models that have had watch called on them

