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
