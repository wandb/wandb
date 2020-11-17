---
title: Summary
---

<a name="wandb.sdk.wandb_summary"></a>
# wandb.sdk.wandb\_summary

[[view_source]](https://github.com/wandb/client/blob/88104ce0f95c9cf58676b249510db7ba56efda09/wandb/sdk/wandb_summary.py#L2)

<a name="wandb.sdk.wandb_summary.SummaryDict"></a>
## SummaryDict Objects

```python
@six.add_metaclass(abc.ABCMeta)
class SummaryDict(object)
```

[[view_source]](https://github.com/wandb/client/blob/88104ce0f95c9cf58676b249510db7ba56efda09/wandb/sdk/wandb_summary.py#L21)

dict-like which wraps all nested dictionraries in a SummarySubDict,
and triggers self._root._callback on property changes.

<a name="wandb.sdk.wandb_summary.Summary"></a>
## Summary Objects

```python
class Summary(SummaryDict)
```

[[view_source]](https://github.com/wandb/client/blob/88104ce0f95c9cf58676b249510db7ba56efda09/wandb/sdk/wandb_summary.py#L82)

Summary tracks single values for each run. By default, summary is set to the
last value of History.

For example, wandb.log({'accuracy': 0.9}) will add a new step to History and
update Summary to the latest value. In some cases, it's more useful to have
the maximum or minimum of a metric instead of the final value. You can set
history manually (wandb.summary['accuracy'] = best_acc).

In the UI, summary metrics appear in the table to compare across runs.
Summary metrics are also used in visualizations like the scatter plot and
parallel coordinates chart.

After training has completed, you may want to save evaluation metrics to a
run. Summary can handle numpy arrays and PyTorch/TensorFlow tensors. When
you save one of these types to Summary, we persist the entire tensor in a
binary file and store high level metrics in the summary object, such as min,
mean, variance, and 95th percentile.

**Examples**:

```
wandb.init(config=args)

best_accuracy = 0
for epoch in range(1, args.epochs + 1):
test_loss, test_accuracy = test()
if (test_accuracy > best_accuracy):
wandb.run.summary["best_accuracy"] = test_accuracy
best_accuracy = test_accuracy
```

<a name="wandb.sdk.wandb_summary.SummarySubDict"></a>
## SummarySubDict Objects

```python
class SummarySubDict(SummaryDict)
```

[[view_source]](https://github.com/wandb/client/blob/88104ce0f95c9cf58676b249510db7ba56efda09/wandb/sdk/wandb_summary.py#L136)

Non-root node of the summary data structure. Contains a path to itself
from the root.

