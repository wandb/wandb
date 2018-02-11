import collections
import os
import psutil
from pynvml import *
import time
from numbers import Number
import threading


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


class SystemStats(object):
    def __init__(self, run):
        try:
            nvmlInit()
            self.gpu_count = nvmlDeviceGetCount()
        except NVMLError as err:
            self.gpu_count = 0
        self.run = run
        self.sampler = {}
        self.samples = 0
        self._shutdown = False
        net = psutil.net_io_counters()
        self.network_init = {
            "sent": net.bytes_sent,
            "recv": net.bytes_recv
        }
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._thread.start()

    def _thread_body(self):
        while True:
            stats = self.stats()
            for stat, value in stats.items():
                if isinstance(value, Number):
                    self.sampler[stat] = self.sampler.get(stat, [])
                    self.sampler[stat].append(value)
            self.samples += 1
            if self._shutdown or self.samples >= 15:
                self.flush()
                if self._shutdown:
                    break
            time.sleep(2)

    def shutdown(self):
        self._shutdown = True
        self._thread.join()

    def flush(self):
        stats = self.stats()
        for stat, value in stats.items():
            # TODO: a bit hacky, we assume all numbers should be averaged.  If you want
            # max for a stat, you must put it in a sub key, like ["network"]["sent"]
            if isinstance(value, Number):
                samples = list(self.sampler.get(stat, [stats[stat]]))
                stats[stat] = round(sum(samples) / len(samples), 2)
        self.run.events.track("system", stats, _wandb=True)
        self.samples = 0
        self.sampler = {}

    def stats(self):
        stats = {}
        for i in range(0, self.gpu_count):
            handle = nvmlDeviceGetHandleByIndex(i)
            try:
                util = nvmlDeviceGetUtilizationRates(handle)
                temp = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
                stats["gpu.{0}.{1}".format(i, "gpu")] = util.gpu
                stats["gpu.{0}.{1}".format(i, "memory")] = util.memory
                stats["gpu.{0}.{1}".format(i, "temp")] = temp
            except NVMLError as err:
                pass
        net = psutil.net_io_counters()
        stats["cpu"] = psutil.cpu_percent()
        stats["memory"] = psutil.virtual_memory().percent
        stats["network"] = {
            "sent": net.bytes_sent - self.network_init["sent"],
            "recv": net.bytes_recv - self.network_init["recv"]
        }
        # TODO: maybe show other partitions, will likely need user to configure
        stats["disk"] = psutil.disk_usage('/').percent
        return stats
