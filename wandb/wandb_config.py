import six


class Config(object):
    def __init__(self):
        object.__setattr__(self, '_items', dict())

    def keys(self):
        return [k for k in self._items.keys() if k != '_wandb']

    def _as_dict(self):
        return self._items

    def __getitem__(self, key):
        return self._items[key]

    def __setitem__(self, key, val):
        self._items[key] = val

    __setattr__ = __setitem__

    def __getattr__(self, key):
        return self.__getitem__(key)

    def update(self, d):
        if isinstance(d, dict):
            self._items.update(d)
        else:
            # assume argparse Namespace
            self._items.update(vars(d))

    def setdefaults(self, d):
        for k, v in six.iteritems(d):
            self._items.setdefault(k, v)
