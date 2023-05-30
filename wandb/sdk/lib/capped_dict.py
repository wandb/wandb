import collections


class CappedDict(collections.OrderedDict):
    default_max_size = 50

    def __init__(self, *args, **kwargs):
        self.max_size = kwargs.pop("max_size", self.default_max_size)
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, val):
        if key not in self:
            max_size = self.max_size - 1
            self._prune_dict(max_size)
        super().__setitem__(key, val)

    def update(self, **kwargs):
        super().update(**kwargs)
        self._prune_dict(self.max_size)

    def _prune_dict(self, max_size):
        if len(self) >= max_size:
            diff = len(self) - max_size
            for k in list(self.keys())[:diff]:
                del self[k]
