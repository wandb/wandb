from __future__ import absolute_import

import logging
import os
from subprocess import PIPE, Popen
import threading

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
        self._tpu_utilization = 0
        self._stop_thread = False
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.start()

    def _thread_body(self):
        while not self._stop_thread:
            self._tpu_utilization = self._get_tpu_utilization()

    def _get_tpu_utilization(self):
        # blocking
        args = [
            "capture_tpu_profile",
            "--tpu=" + os.environ["TPU_NAME"],
            "--monitoring_level=2",
            "--num_queries=1",
            "--duration_ms=100",
        ]
        try:
            p = Popen(args, stdout=PIPE, stderr=None, universal_newlines=True)
            return float(
                p.stdout.read().split("Utilization ")[1].split(": ")[1].split("%")[0]
            )
        except Exception:
            return 0.0

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
