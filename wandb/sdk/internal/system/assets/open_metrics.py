import logging
import multiprocessing as mp
from collections import defaultdict, deque
from hashlib import md5
from typing import TYPE_CHECKING, Dict, List, Union

import requests
import wandb
from .aggregators import aggregate_last, aggregate_mean
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

    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url
        self.session = requests.Session()
        self.samples: "Deque[dict]" = deque([])
        # {"<metric name>": {"<labels hash>": <index>}}
        self.label_map: "Dict[str, Dict[str, int]]" = defaultdict(dict)
        self.label_hashes: "Dict[str, dict]" = {}

    def parse_open_metrics_endpoint(self) -> Dict[str, Union[str, int, float]]:
        assert prometheus_client_parser is not None
        response = self.session.get(self.url)
        measurement = {}
        for family in prometheus_client_parser.text_string_to_metric_families(
            response.text
        ):
            if family.type not in ("counter", "gauge"):
                # todo: add support for other metric types?
                # todo: log warning about that?
                continue

            for sample in family.samples:
                # md5 hash of the labels
                label_hash = md5(str(sample.labels).encode("utf-8")).hexdigest()
                if label_hash not in self.label_map[sample.name]:
                    self.label_map[sample.name][label_hash] = len(
                        self.label_map[sample.name]
                    )
                    self.label_hashes[label_hash] = sample.labels
                index = self.label_map[sample.name][label_hash]
                measurement[f"{sample.name}.{index}"] = sample.value

        return measurement

    def sample(self) -> None:
        sample = self.parse_open_metrics_endpoint()
        self.samples.append(sample)
        # print(self.label_map)
        # print(self.samples)
        # print(self.label_hashes)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}

        stats = {}
        for key in self.samples[0].keys():
            samples = [s[key] for s in self.samples if key in s]
            if samples and all(isinstance(s, (int, float)) for s in samples):
                stats[f"{self.name}.{key}"] = aggregate_mean(samples)
            else:
                stats[f"{self.name}.{key}"] = aggregate_last(samples)
        # print(stats)
        return stats


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

        self.metrics: List[Metric] = [OpenMetricsMetric(name, url)]

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
        except Exception as e:
            logger.debug(
                f"OpenMetrics endpoint {url} is not available: {e}", exc_info=True
            )

        return False

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        # todo: also return self.label_hashes
        return {self.name: self.url}
