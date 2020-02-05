
class DataStore(object):
    def __init__(self):
        self._fp = None

    def open(self, fname):
        self._fp = open(fname, "wb")

    def write(self, obj):
        pass

    def close(self):
        if self._fp is not None:
            self._fp.close()
