import logging
import multiprocessing
import os

try:
    from tensorflow.python.distribute.cluster_resolver import tpu_cluster_resolver  # type: ignore
    from tensorflow.python.profiler import profiler_client  # type: ignore
except ImportError:
    tpu_cluster_resolver = None
    profiler_client = None
    pass


logger = logging.getLogger(__name__)


class TPUProfiler(object):
    def __init__(
        self,
        service_addr=None,
        tpu=None,
        tpu_zone=None,
        gcp_project=None,
        duration_ms=1000,
    ):
        if service_addr:
            if tpu:
                logger.warn(
                    "Both service_addr and tpu arguments provided. "
                    "Ignoring tpu and using service_addr."
                )
        else:
            if not tpu:
                tpu = os.environ["TPU_NAME"]
            try:
                service_addr = tpu_cluster_resolver.TPUClusterResolver(
                    [tpu], zone=tpu_zone, project=gcp_project
                ).get_master()
            except (ValueError, TypeError):
                raise Exception(
                    "Failed to find TPU. Use tpu_zone and gcp_project "
                    "arguments to specify zone and project for your TPU."
                )
        service_addr = service_addr.replace("grpc://", "").replace(":8470", ":8466")
        self.service_addr = service_addr
        self.duration_ms = duration_ms
        self._manager = multiprocessing.Manager()
        self._dict = self._manager.dict()
        self._dict["tpu_utilization"] = 0.0
        self._process = multiprocessing.Process(
            target=self._loop, args=(self._dict), daemon=True
        )
        self._process.start()

    def _get_tpu_utilization(self):
        # this call blocks for duration_ms milliseconds
        res = profiler_client.monitor(
            self.service_addr, duration_ms=self.duration_ms, level=2
        )
        return float(res.split("Utilization ")[1].split(": ")[1].split("%")[0])

    def _loop(self, dict_):
        while True:
            try:
                dict_["tpu_utilization"] = self._get_tpu_utilization()
            except Exception:
                pass

    def get_tpu_utilization(self):
        if self._process is None:
            raise Exception("This TPUProfiler instance has been stopped.")
        if not self._process.is_alive():
            raise Exception("TPUProfiler background process shutdown!")
        return self._dict["tpu_utilization"]

    def stop(self):
        if self._process and self._process.is_alive():
            self._process.terminate()
        self._process = None


def is_tpu_available():
    return profiler_client is not None and "TPU_NAME" in os.environ
