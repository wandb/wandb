import logging
import os
import threading
import time


logger = logging.getLogger(__name__)


class TPUProfiler:
    def __init__(
        self,
        service_addr=None,
        tpu=None,
        tpu_zone=None,
        gcp_project=None,
        duration_ms=1000,
    ):
        from tensorflow.python.distribute.cluster_resolver import tpu_cluster_resolver  # type: ignore
        from tensorflow.python.profiler import profiler_client  # type: ignore

        if service_addr:
            if tpu:
                logger.warn(
                    "Both service_addr and tpu arguments provided. "
                    "Ignoring tpu and using service_addr."
                )
        else:
            if not tpu:
                tpu = os.environ.get("TPU_NAME")
                if tpu is None:
                    raise Exception("Required environment variable TPU_NAME.")
            if tpu_zone is None:
                tpu_zone = os.environ.get("CLOUDSDK_COMPUTE_ZONE")
            if gcp_project is None:
                gcp_project = os.environ.get("CLOUDSDK_CORE_PROJECT")
            try:
                service_addr = tpu_cluster_resolver.TPUClusterResolver(
                    [tpu], zone=tpu_zone, project=gcp_project
                ).get_master()
            except (ValueError, TypeError):
                raise Exception(
                    "Failed to find TPU. Try specifying TPU zone "
                    "(via CLOUDSDK_COMPUTE_ZONE environment variable)"
                    " and GCP project (via CLOUDSDK_CORE_PROJECT "
                    "environment variable)."
                )
        service_addr = service_addr.replace("grpc://", "").replace(":8470", ":8466")
        self.service_addr = service_addr
        self.duration_ms = duration_ms
        self._tpu_utilization = None
        self._stop = True
        self._profiler_client = profiler_client
        self.start()

    def _get_tpu_utilization(self):
        # this call blocks for duration_ms milliseconds
        res = self._profiler_client.monitor(
            self.service_addr, duration_ms=self.duration_ms, level=2
        )
        return float(res.split("Utilization ")[1].split(": ")[1].split("%")[0])

    def _loop(self):
        while not self._stop:
            time.sleep(0.5)
            try:
                self._tpu_utilization = self._get_tpu_utilization()
            except Exception:
                time.sleep(1)

    def get_tpu_utilization(self):
        return self._tpu_utilization

    def stop(self):
        if not self._stop:
            self._stop = True
            self._thread.join()

    def start(self):
        if self._stop:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._stop = False
            self._thread.start()


def is_tpu_available() -> bool:
    tpu_name = os.environ.get("TPU_NAME", False)

    if tpu_name is False:
        return False

    try:
        from tensorflow.python.distribute.cluster_resolver import tpu_cluster_resolver  # type: ignore # noqa
        from tensorflow.python.profiler import profiler_client  # type: ignore # noqa
    except (
        ImportError,
        TypeError,
        AttributeError,
    ):  # Saw type error when iterating paths on colab...
        # TODO: Saw sentry error (https://sentry.io/organizations/weights-biases/issues/2699838212/?project=5288891&query=firstRelease%3A0.12.4&statsPeriod=14d) where
        # module 'tensorflow.python.pywrap_tensorflow' has no attribute 'TFE_DEVICE_PLACEMENT_EXPLICIT'
        return False

    return True


# Avoid multiple TPUProfiler instances

_INSTANCE = None


def get_profiler(*args, **kwargs):
    # NOTE: Only arguments from the first call to this method is used.
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = TPUProfiler(*args, **kwargs)
    return _INSTANCE
