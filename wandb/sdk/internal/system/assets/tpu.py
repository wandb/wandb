import logging
import os
import threading
from collections import deque
from typing import TYPE_CHECKING, List, Optional

from .aggregators import aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic

logger = logging.getLogger(__name__)


class TPUUtilization:
    """Google Cloud TPU utilization in percent."""

    name = "tpu"
    samples: "Deque[float]"

    def __init__(
        self,
        service_addr: str,
        duration_ms: int = 100,
    ) -> None:
        self.samples = deque([])

        self.duration_ms = duration_ms
        self.service_addr = service_addr

        try:
            from tensorflow.python.profiler import profiler_client  # type: ignore

            self._profiler_client = profiler_client
        except ImportError:
            logger.warning(
                "Unable to import `tensorflow.python.profiler.profiler_client`. "
                "TPU metrics will not be reported."
            )
            self._profiler_client = None

    def sample(self) -> None:
        result = self._profiler_client.monitor(
            self.service_addr, duration_ms=self.duration_ms, level=2
        )

        self.samples.append(
            float(result.split("Utilization ")[1].split(": ")[1].split("%")[0])
        )

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


@asset_registry.register
class TPU:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.service_addr = self.get_service_addr()
        self.metrics: List[Metric] = [TPUUtilization(self.service_addr)]

        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @staticmethod
    def get_service_addr(
        service_addr: Optional[str] = None,
        tpu_name: Optional[str] = None,
        compute_zone: Optional[str] = None,
        core_project: Optional[str] = None,
    ) -> str:
        if service_addr is not None:
            if tpu_name is not None:
                logger.warn(
                    "Both service_addr and tpu_name arguments provided. "
                    "Ignoring tpu_name and using service_addr."
                )
        else:
            tpu_name = tpu_name or os.environ.get("TPU_NAME")
            if tpu_name is None:
                raise Exception("Required environment variable TPU_NAME.")
            compute_zone = compute_zone or os.environ.get("CLOUDSDK_COMPUTE_ZONE")
            core_project = core_project or os.environ.get("CLOUDSDK_CORE_PROJECT")
            try:
                from tensorflow.python.distribute.cluster_resolver import (  # type: ignore
                    tpu_cluster_resolver,
                )

                service_addr = tpu_cluster_resolver.TPUClusterResolver(
                    [tpu_name], zone=compute_zone, project=core_project
                ).get_master()
            except (ValueError, TypeError):
                raise ValueError(
                    "Failed to find TPU. Try specifying TPU zone "
                    "(via CLOUDSDK_COMPUTE_ZONE environment variable)"
                    " and GCP project (via CLOUDSDK_CORE_PROJECT "
                    "environment variable)."
                )
        service_addr = service_addr.replace("grpc://", "").replace(":8470", ":8466")
        return service_addr

    def start(self) -> None:
        if self.metrics:
            self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    @classmethod
    def is_available(cls) -> bool:
        if os.environ.get("TPU_NAME", False) is False:
            return False

        try:
            from tensorflow.python.distribute.cluster_resolver import (  # noqa: F401
                tpu_cluster_resolver,
            )
            from tensorflow.python.profiler import profiler_client  # noqa: F401

            cls.get_service_addr()
        except (
            ImportError,
            TypeError,
            AttributeError,
            ValueError,
        ):  # Saw type error when iterating paths on colab...
            # TODO: Saw error in sentry where module 'tensorflow.python.pywrap_tensorflow'
            #  has no attribute 'TFE_DEVICE_PLACEMENT_EXPLICIT'
            return False

        return True

    def probe(self) -> dict:
        return {self.name: {"service_address": self.service_addr}}
