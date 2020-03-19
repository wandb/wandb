class Stats(object):
    def __init__(self):
        self._stats = {}

    def add_deduped_file(self, save_name, size):
        self._stats[save_name] = {
            'deduped': True,
            'total': size,
            'uploaded': size,
            'failed': False
        }

    def add_uploaded_file(self, save_name, size):
        self._stats[save_name] = {
            'deduped': False,
            'total': size,
            'uploaded': 0,
            'failed': False
        }

    def update_uploaded_file(self, save_name, total_uploaded):
        self._stats[save_name]['uploaded'] = total_uploaded

    def summary(self):
        stats = list(self._stats.values())
        return {
            'nfiles': len(stats),
            'uploaded_bytes': sum(f['uploaded'] for f in stats),
            'total_bytes': sum(f['total'] for f in stats),
            'deduped_bytes': sum(f['total'] for f in stats if f['deduped'])
        }

    def files(self):
        return self._stats.keys()