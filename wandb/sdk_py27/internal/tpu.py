from __future__ import absolute_import

import logging
import os
from subprocess import PIPE, Popen, STDOUT
import threading
import time

import wandb

logger = logging.getLogger(__name__)


class TPUProfiler(object):
    def __init__(self):
        try:
            import cloud_tpu_profiler  # type: ignore
            del cloud_tpu_profiler  # flake8
            self._enabled = True
        except ImportError:
            wandb.termwarn(
                "cloud_tpu_profiler is not installed. "
                "TPU stats will not be captured."
            )
            logger.warn(
                "cloud_tpu_profiler is not installed. "
                "TPU stats will not be captured."
            )
            self._enabled = False
            return
        self._tpu_utilization = 0.0
        self._start_capture_process()
        self._stop_thread = False
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.start()

    def _start_capture_process(self):
        args = [
            "capture_tpu_profile",
            "--tpu=" + os.environ["TPU_NAME"],
            "--monitoring_level=2",
            "--num_queries=100",
        ]
        self._capture_process = Popen(
            args, stdout=PIPE, stderr=STDOUT, universal_newlines=True
        )

    def _is_capture_process_alive(self):
        return self._capture_process.poll() is None

    def _readline(self):
        if not self._is_capture_process_alive():
            self._start_capture_process()
        return self._capture_process.stdout.readline()

    def _thread_body(self):
        while not self._stop_thread:
            line = self._readline()
            if line.startswith("Utilization "):
                self._tpu_utilization = float(line.split(": ")[1].split("%")[0])
                self._time = time.time()
                continue

    def get_tpu_utilization(self):
        return self._tpu_utilization

    def stop(self):
        if self._enabled:
            self._stop_thread = True
            self._thread.join()

    def is_enabled(self):
        return self._enabled


def is_tpu_available():
    return "TPU_NAME" in os.environ
