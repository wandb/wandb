import abc

import six
import wandb
from wandb.interface.summary_record import SummaryItem, SummaryRecord

if wandb.TYPE_CHECKING:  # type: ignore
    import typing as t


def _get_dict(d):
    if isinstance(d, dict):
        return d
    # assume argparse Namespace
    return vars(d)


@six.add_metaclass(abc.ABCMeta)
class SummaryDict(object):
    """dict-like which wraps all nested dictionraries in a SummarySubDict,
     and triggers self._root._callback on property changes."""

    @abc.abstractmethod
    def _as_dict(self):
        raise NotImplementedError

    @abc.abstractmethod
    def _update(self, record: SummaryRecord):
        raise NotImplementedError

    def keys(self):
        return [k for k in self._as_dict().keys() if k != "_wandb"]

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
        for key, value in six.iteritems(d):
            item = SummaryItem()
            item.key = (key,)
            item.value = value
            record.update = (item,)

        self._update(record)


class Summary(SummaryDict):
    """Root node of the summary data structure. Contains the callback."""

    _update_callback: t.Callable
    _get_current_summary_callback: t.Callable

    def __init__(self, get_current_summary_callback: t.Callable):
        super(Summary, self).__init__()
        object.__setattr__(self, "_update_callback", None)
        object.__setattr__(
            self, "_get_current_summary_callback", get_current_summary_callback
        )

    def _set_update_callback(self, update_callback: t.Callable):
        object.__setattr__(self, "_update_callback", update_callback)

    def _as_dict(self):
        return self._get_current_summary_callback()

    def _update(self, record: SummaryRecord):
        if self._update_callback:
            self._update_callback(record)


class SummarySubDict(SummaryDict):
    """Non-root node of the summary data structure. Contains a path to itself
    from the root."""

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
