---
title: Summary
---

<a name="wandb.sdk.wandb_summary"></a>
# wandb.sdk.wandb\_summary

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L2)

<a name="wandb.sdk.wandb_summary.SummaryDict"></a>
## SummaryDict Objects

```python
@six.add_metaclass(abc.ABCMeta)
class SummaryDict(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L21)

dict-like which wraps all nested dictionraries in a SummarySubDict,
and triggers self._root._callback on property changes.

<a name="wandb.sdk.wandb_summary.SummaryDict.keys"></a>
#### keys

```python
 | keys()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L33)

<a name="wandb.sdk.wandb_summary.SummaryDict.get"></a>
#### get

```python
 | get(key, default=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L36)

<a name="wandb.sdk.wandb_summary.SummaryDict.__getitem__"></a>
#### \_\_getitem\_\_

```python
 | __getitem__(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L39)

<a name="wandb.sdk.wandb_summary.SummaryDict.__getattr__"></a>
#### \_\_getattr\_\_

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L54)

<a name="wandb.sdk.wandb_summary.SummaryDict.__setitem__"></a>
#### \_\_setitem\_\_

```python
 | __setitem__(key, val)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L56)

<a name="wandb.sdk.wandb_summary.SummaryDict.__setattr__"></a>
#### \_\_setattr\_\_

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L59)

<a name="wandb.sdk.wandb_summary.SummaryDict.__delattr__"></a>
#### \_\_delattr\_\_

```python
 | __delattr__(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L61)

<a name="wandb.sdk.wandb_summary.SummaryDict.__delitem__"></a>
#### \_\_delitem\_\_

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L68)

<a name="wandb.sdk.wandb_summary.SummaryDict.update"></a>
#### update

```python
 | update(d: t.Dict)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L70)

<a name="wandb.sdk.wandb_summary.Summary"></a>
## Summary Objects

```python
class Summary(SummaryDict)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L82)

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

<a name="wandb.sdk.wandb_summary.Summary.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(get_current_summary_callback: t.Callable)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L118)

<a name="wandb.sdk.wandb_summary.SummarySubDict"></a>
## SummarySubDict Objects

```python
class SummarySubDict(SummaryDict)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L136)

Non-root node of the summary data structure. Contains a path to itself
from the root.

<a name="wandb.sdk.wandb_summary.SummarySubDict.__init__"></a>
#### \_\_init\_\_

```python
 | __init__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_summary.py#L144)

