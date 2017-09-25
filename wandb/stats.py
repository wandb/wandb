import collections
import os

class FileStats(object):
    def __init__(self, file_path):
        self._file_path = file_path
        self.size = 0
        self.uploaded = 0
    
    def update_size(self):
        self.size = os.path.getsize(self._file_path)


class Stats(object):
    def __init__(self):
        self._files = {}

    def update_file(self, file_path):
        if file_path not in self._files:
            self._files[file_path] = FileStats(file_path)
        self._files[file_path].update_size()

    def update_all_files(self):
        for file_stats in self._files.values():
            file_stats.update_size()

    def update_progress(self, file_path, uploaded):
        if file_path in self._files:
            self._files[file_path].uploaded = uploaded

    def files(self):
        return self._files.keys()

    def stats(self):
        return self._files

    def summary(self):
        return {
            'completed_files': sum(f.size == f.uploaded for f in self._files.values()),
            'total_files': len(self._files),
            'uploaded_bytes': sum(f.uploaded for f in self._files.values()),
            'total_bytes': sum(f.size for f in self._files.values())
        }