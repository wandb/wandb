import abc
import typing as t

from .interface.summary_record import SummaryItem, SummaryRecord


def _get_dict(d):
    if isinstance(d, dict):
        return d
    # assume argparse Namespace
    return vars(d)


class SummaryDict(metaclass=abc.ABCMeta):
    """dict-like wrapper for the nested dictionaries in a SummarySubDict.

    Triggers self._root._callback on property changes.
    """

    @abc.abstractmethod
    def _as_dict(self):
        raise NotImplementedError

    @abc.abstractmethod
    def _update(self, record: SummaryRecord):
        raise NotImplementedError

    def keys(self):
        return [k for k in self._as_dict().keys() if k != "_wandb"]

    def get(self, key, default=None):
        return self._as_dict().get(key, default)

    def __getitem__(self, key):
        item = self._as_dict()[key]

        if isinstance(item, dict):
            # this nested dict needs to be wrapped:
            wrapped_item = SummarySubDict()
            object.__setattr__(wrapped_item, "_items", item)
            object.__setattr__(wrapped_item, "_parent", self)
            object.__setattr__(wrapped_item, "_parent_key", key)

            return wrapped_item

        # this item isn't a nested dict
        return item

    __getattr__ = __getitem__

    def __setitem__(self, key, val):
        self.update({key: val})

    __setattr__ = __setitem__

    def __delattr__(self, key):
        record = SummaryRecord()
        item = SummaryItem()
        item.key = (key,)
        record.remove = (item,)
        self._update(record)

    __delitem__ = __delattr__

    def update(self, d: t.Dict):
        # import ipdb; ipdb.set_trace()
        record = SummaryRecord()
        for key, value in d.items():
            item = SummaryItem()
            item.key = (key,)
            item.value = value
            record.update.append(item)

        self._update(record)


class Summary(SummaryDict):
    """Track single values for each metric for each run.

    By default, a metric's summary is the last value of its History.

    For example, `wandb.log({'accuracy': 0.9})` will add a new step to History and
    update Summary to the latest value. In some cases, it's more useful to have
    the maximum or minimum of a metric instead of the final value. You can set
    history manually `(wandb.summary['accuracy'] = best_acc)`.

    In the UI, summary metrics appear in the table to compare across runs.
    Summary metrics are also used in visualizations like the scatter plot and
    parallel coordinates chart.

    After training has completed, you may want to save evaluation metrics to a
    run. Summary can handle numpy arrays and PyTorch/TensorFlow tensors. When
    you save one of these types to Summary, we persist the entire tensor in a
    binary file and store high level metrics in the summary object, such as min,
    mean, variance, and 95th percentile.

    Examples:
        ```python
        wandb.init(config=args)

        best_accuracy = 0
        for epoch in range(1, args.epochs + 1):
            test_loss, test_accuracy = test()
            if test_accuracy > best_accuracy:
                wandb.run.summary["best_accuracy"] = test_accuracy
                best_accuracy = test_accuracy
        ```
    """

    _update_callback: t.Callable
    _get_current_summary_callback: t.Callable

    def __init__(self, get_current_summary_callback: t.Callable):
        super().__init__()
        object.__setattr__(self, "_update_callback", None)
        object.__setattr__(
            self, "_get_current_summary_callback", get_current_summary_callback
        )

    def _set_update_callback(self, update_callback: t.Callable):
        object.__setattr__(self, "_update_callback", update_callback)

    def _as_dict(self):
        return self._get_current_summary_callback()

    def _update(self, record: SummaryRecord):
        if self._update_callback:  # type: ignore
            self._update_callback(record)


class SummarySubDict(SummaryDict):
    """Non-root node of the summary data structure.

    Contains a path to itself from the root.
    """

    _items: t.Dict
    _parent: SummaryDict
    _parent_key: str

    def __init__(self):
        object.__setattr__(self, "_items", dict())
        object.__setattr__(self, "_parent", None)
        object.__setattr__(self, "_parent_key", None)

    def _as_dict(self):
        return self._items

    def _update(self, record: SummaryRecord):
        return self._parent._update(record._add_next_parent(self._parent_key))
