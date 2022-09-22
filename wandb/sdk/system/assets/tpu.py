import logging
import multiprocessing as mp
import os
from collections import deque
from typing import TYPE_CHECKING, Deque, Optional, cast

from .interfaces import MetricType, MetricsMonitor
from . import asset_registry


if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic

logger = logging.getLogger(__name__)

# TODO: just copied from old tpu code, maybe need restructuring...


class TPUUtilization:
    name = "tpu.utilization"
    metric_type = cast("gauge", MetricType)
    samples: Deque[float]

    def __init__(
        self,
        service_addr: str,
        duration_ms: int = 1000,
    ) -> None:
        self.samples = deque([])

        self.duration_ms = duration_ms
        self.service_addr = service_addr

        from tensorflow.python.profiler import profiler_client

        self._profiler_client = profiler_client

    def sample(self) -> None:
        result = self._profiler_client.monitor(
            self.service_addr, duration_ms=self.duration_ms, level=2
        )

        self.samples.append(
            float(result.split("Utilization ")[1].split(": ")[1].split("%")[0])
        )

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class TPU:
    def __init__(
        self,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics = []
        try:
            service_addr = self.get_service_addr()
            self.metrics.append(TPUUtilization(service_addr))
        except Exception as e:
            logger.warn("Failed to initialize TPU metrics: %s", e)

        self.metrics_monitor = MetricsMonitor(
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
                raise Exception(
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
            from tensorflow.python.distribute.cluster_resolver import (  # type: ignore # noqa
                tpu_cluster_resolver,
            )
            from tensorflow.python.profiler import (  # type: ignore # noqa
                profiler_client,
            )
        except (
            ImportError,
            TypeError,
            AttributeError,
        ):  # Saw type error when iterating paths on colab...
            # TODO: Saw sentry error (https://sentry.io/organizations/weights-biases/issues/2699838212/?project=5288891&query=firstRelease%3A0.12.4&statsPeriod=14d) where
            # module 'tensorflow.python.pywrap_tensorflow' has no attribute 'TFE_DEVICE_PLACEMENT_EXPLICIT'
            return False

        return True

    def probe(self) -> dict:
        return {}
