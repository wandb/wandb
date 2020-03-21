import six


def _get_dict(d):
    if isinstance(d, dict):
        return d
    # assume argparse Namespace
    return vars(d)


# TODO(jhr): consider a callback for persisting changes?
# if this is done right we might make sure this is pickle-able
# we might be able to do this on other objects like Run?
class Summary(object):
    def __init__(self):
        object.__setattr__(self, '_items', dict())
        object.__setattr__(self, '_callback', None)

    def _set_callback(self, cb):
        object.__setattr__(self, '_callback', cb)

    def keys(self):
        return [k for k in self._items.keys() if k != '_wandb']

    def _as_dict(self):
        return self._items

    def __getitem__(self, key):
        return self._items[key]

    def __setitem__(self, key, val):
        self._items[key] = val
        if self._callback:
            self._callback(key=key, val=val, data=dict(self))

    __setattr__ = __setitem__

    def __getattr__(self, key):
        return self.__getitem__(key)

    def update(self, d):
        self._items.update(_get_dict(d))
        if self._callback:
            self._callback(data=dict(self))

    def setdefaults(self, d):
        d = _get_dict(d)
        for k, v in six.iteritems(d):
            self._items.setdefault(k, v)
        if self._callback:
            self._callback(data=dict(self))
