class RecordsUtil:
    def __init__(self, q):
        self._q = q
        self._data = []
        self._read_all()

    def _read_all(self):
        while not self._q.empty():
            self._data.append(self._q.get())

    def _get_all(self, record_type=None):
        for r in self._data:
            r_type = r.WhichOneof("record_type")
            if not record_type or r_type == record_type:
                if r_type:
                    r = getattr(r, r_type)
                yield r

    @property
    def records(self):
        return list(self._get_all())

    @property
    def configs(self):
        return list(self._get_all("config"))

    @property
    def summary(self):
        return list(self._get_all("summary"))

    @property
    def history(self):
        return list(self._get_all("history"))

    @property
    def metric(self):
        return list(self._get_all("metric"))
