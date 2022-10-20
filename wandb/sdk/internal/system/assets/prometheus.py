from collections import deque
import multiprocessing as mp
from typing import TYPE_CHECKING, List

import requests
import wandb
from .aggregators import aggregate_last
from .interfaces import (
    Interface,
    Metric,
    MetricType,
    MetricsMonitor,
)

if TYPE_CHECKING:
    from typing import Deque
    from wandb.sdk.internal.settings_static import SettingsStatic


try:
    import prometheus_client.parser as prometheus_client_parser  # type: ignore
except ImportError:
    prometheus_client_parser = None


class PrometheusMetric:
    """
    Container for all the COUNTER and GAUGE metrics extracted from the
    prometheus metrics endpoint.
    """

    metric_type: MetricType = "gauge"

    def __init__(self, url: str) -> None:
        self.name = f"prometheus::{url}"
        self.url = url
        self.session = requests.Session()
        self.samples: "Deque[float]" = deque([])

    def parse_prometheus_metrics_endpoint(self) -> None:
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
            # if family.type == "gauge":
            #     print("Name: {0} Labels: {1} Value: {2}".format(*sample))

            # follow this white rabbit:
            # x = {
            #     "promhttp_metric_handler_requests_total": {
            #         "type": "counter",
            #         "samples": [
            #             {
            #                 "labels": {
            #                     "code": "200",
            #                     "handler": "prometheus",
            #                 },
            #                 "value": 1.0,
            #             },
            #         ]
            #     }
            # }

    def sample(self) -> None:
        ...
        # sample = ...
        # self.samples.append(sample)
        self.parse_prometheus_metrics_endpoint()

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        # todo: create a statistics class with helper methods to compute
        #      mean, median, min, max, etc.
        if not self.samples:
            return {}
        aggregate = aggregate_last(self.samples)
        return {self.name: aggregate}


class Prometheus:
    # Poll a prometheus endpoint, parse the response and return a dict of metrics
    # Implements the same Protocol interface as Asset
    name: str
    metrics: List[Metric]
    metrics_monitor: "MetricsMonitor"

    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: mp.synchronize.Event,
        url: str = "",
    ) -> None:
        self.name = f"{self.__class__.__name__.lower()}::{url}"
        self.url = url
        self.interface = interface
        self.settings = settings
        self.shutdown_event = shutdown_event

        self.metrics: List[Metric] = [PrometheusMetric(url)]

        self.metrics_monitor: "MetricsMonitor" = MetricsMonitor(
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @classmethod
    def is_available(cls) -> bool:
        ret = prometheus_client_parser is not None
        if not ret:
            wandb.termwarn(
                "Monitoring Prometheus endpoints requires the `prometheus_client` package. "
                "To get it, run `pip install prometheus_client`.",
                repeat=False,
            )
        return ret

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        return {self.name: self.url}
