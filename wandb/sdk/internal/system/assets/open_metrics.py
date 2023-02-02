import logging
import multiprocessing as mp
from collections import deque
from typing import TYPE_CHECKING, Dict, List

import requests
import wandb
from .aggregators import aggregate_last
from .interfaces import (
    Interface,
    Metric,
    MetricsMonitor,
)

if TYPE_CHECKING:
    from typing import Deque
    from wandb.sdk.internal.settings_static import SettingsStatic


logger = logging.getLogger(__name__)


try:
    import prometheus_client.parser as prometheus_client_parser  # type: ignore
except ImportError:
    prometheus_client_parser = None


class OpenMetricsMetric:
    """
    Container for all the COUNTER and GAUGE metrics extracted from an
    OpenMetrics endpoint.
    """

    def __init__(self, url: str) -> None:
        self.name = f"OpenMetrics::{url}"
        self.url = url
        self.session = requests.Session()
        self.samples: "Deque[dict]" = deque([])
        # {"<metric name>": {"<hash>": <index>}}
        self.label_map: "Dict[str, Dict[str, int]]" = {}
        # {name}.{metric.name}.{<index from label_map>}: {value, timestamp, exemplar}

    def parse_open_metrics_endpoint(self) -> None:
        assert prometheus_client_parser is not None
        response = self.session.get(self.url)
        # print(response.text)
        for family in prometheus_client_parser.text_string_to_metric_families(
            response.text
        ):
            print(family.type)
            if family.type == "counter":
                print(family.samples)
            # for sample in family.samples:
            #     if sample.timestamp is not None:
            #         print(sample)
            if family.type == "gauge":
                for sample in family.samples:
                    print(sample)
                print()

            # follow this white rabbit:
            """
            convert to an object:
            {
                "DCGM_FI_DEV_GPU_UTIL": {
                    "<hash_0>": {
                        "samples": [...],  # extract values and append to this list
                        "type": "gauge",
                        "labels": {...},
                    },
                },
                "DCGM_FI_DEV_POWER_USAGE": {
                    ...
                },
            }



            {
                "DCGM_FI_DEV_GPU_UTIL": [
                    {
                        "labels": {
                            "gpu": "0",
                            "UUID": "GPU-c601d117-58ff-cd30-ae20-529ab192ba51",
                            ...
                        },
                        "hash": "<hash the labels to ease aggregation downstream?>",
                        "value": 33.0,
                        "timestamp": None,
                        "exemplar": None,
                    },
                    {
                        "labels": {
                            "gpu": "1",
                            "UUID": "GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e",
                            ...
                        },
                        "hash": "<hash the labels to ease aggregation downstream?>",
                        "value": 99.0,
                        "timestamp": None,
                        "exemplar": None,
                    },
                ],
                "DCGM_FI_DEV_POWER_USAGE": [
                    {
                        "labels": {
                            "gpu": "0",
                            "UUID": "GPU-c601d117-58ff-cd30-ae20-529ab192ba51",
                            ...
                        },
                        "hash": "<hash the labels to ease aggregation downstream?>",
                        "value": 14.27,
                        "timestamp": None,
                        "exemplar": None,
                    },
                    {
                        "labels": {
                            "gpu": "1",
                            "UUID": "GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e",
                            ...
                        },
                        "hash": "<hash the labels to ease aggregation downstream?>",
                        "value": 69.652,
                        "timestamp": None,
                        "exemplar": None,
                    }
                ],
            }
            """

    def sample(self) -> None:
        ...
        # sample = ...
        # self.samples.append(sample)
        self.parse_open_metrics_endpoint()

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_last(self.samples)
        return {self.name: aggregate}


class OpenMetrics:
    # Poll an OpenMetrics endpoint, parse the response and return a dict of metrics
    # Implements the same Protocol interface as Asset

    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: mp.synchronize.Event,
        name: str,
        url: str,
    ) -> None:
        self.name = name
        self.url = url
        self.interface = interface
        self.settings = settings
        self.shutdown_event = shutdown_event

        self.metrics: List[Metric] = [OpenMetricsMetric(url)]

        self.metrics_monitor: "MetricsMonitor" = MetricsMonitor(
            asset_name=self.name,
            metrics=self.metrics,
            interface=interface,
            settings=settings,
            shutdown_event=shutdown_event,
        )

    @staticmethod
    def is_available(url: str) -> bool:
        ret = prometheus_client_parser is not None
        if not ret:
            wandb.termwarn(
                "Monitoring OpenMetrics endpoints requires the `prometheus_client` package. "
                "To get it, run `pip install prometheus_client`.",
                repeat=False,
            )
            return False
        # check if the endpoint is available and is a valid OpenMetrics endpoint
        try:
            response = requests.get(url)
            if (
                response.status_code == 200
                and prometheus_client_parser.text_string_to_metric_families(
                    response.text
                )
            ):
                return True
        except Exception:
            logger.debug(f"OpenMetrics endpoint {url} is not available", exc_info=True)
            return False

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        return {self.name: self.url}
