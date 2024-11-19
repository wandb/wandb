import logging
import re
import threading
from collections import defaultdict, deque
from functools import lru_cache
from types import ModuleType
from typing import TYPE_CHECKING, Dict, Final, List, Mapping, Sequence, Tuple, Union

import requests
import requests.adapters
import urllib3

import wandb
from wandb.sdk.lib import hashutil, telemetry

from .aggregators import aggregate_last, aggregate_mean
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque, Optional

    from wandb.sdk.internal.settings_static import SettingsStatic


_PREFIX: Final[str] = "openmetrics"

_REQUEST_RETRY_STRATEGY = urllib3.util.retry.Retry(
    backoff_factor=1,
    total=3,
    status_forcelist=(408, 409, 429, 500, 502, 503, 504),
)
_REQUEST_POOL_CONNECTIONS = 4
_REQUEST_POOL_MAXSIZE = 4
_REQUEST_TIMEOUT = 3


logger = logging.getLogger(__name__)


prometheus_client_parser: "Optional[ModuleType]" = None
try:
    import prometheus_client.parser  # type: ignore

    prometheus_client_parser = prometheus_client.parser
except ImportError:
    pass


def _setup_requests_session() -> requests.Session:
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        max_retries=_REQUEST_RETRY_STRATEGY,
        pool_connections=_REQUEST_POOL_CONNECTIONS,
        pool_maxsize=_REQUEST_POOL_MAXSIZE,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _nested_dict_to_tuple(
    nested_dict: Mapping[str, Mapping[str, str]],
) -> Tuple[Tuple[str, Tuple[str, str]], ...]:
    return tuple((k, *v.items()) for k, v in nested_dict.items())  # type: ignore


def _tuple_to_nested_dict(
    nested_tuple: Tuple[Tuple[str, Tuple[str, str]], ...],
) -> Dict[str, Dict[str, str]]:
    return {k: dict(v) for k, *v in nested_tuple}


@lru_cache(maxsize=128)
def _should_capture_metric(
    endpoint_name: str,
    metric_name: str,
    metric_labels: Tuple[str, ...],
    filters: Tuple[Tuple[str, Tuple[str, str]], ...],
) -> bool:
    # we use tuples to make the function arguments hashable => usable with lru_cache
    should_capture = False

    if not filters:
        return should_capture

    # self.filters keys are regexes, check the name against them
    # and for the first match, check the labels against the label filters.
    # assume that if at least one label filter doesn't match, the metric
    # should not be captured.
    # it's up to the user to make sure that the filters are not conflicting etc.
    metric_labels_dict = {t[0]: t[1] for t in metric_labels}
    filters_dict = _tuple_to_nested_dict(filters)
    for metric_name_regex, label_filters in filters_dict.items():
        if not re.match(metric_name_regex, f"{endpoint_name}.{metric_name}"):
            continue

        should_capture = True

        for label, label_filter in label_filters.items():
            if not re.match(label_filter, metric_labels_dict.get(label, "")):
                should_capture = False
                break
        break

    return should_capture


class OpenMetricsMetric:
    """Container for all the COUNTER and GAUGE metrics extracted from an OpenMetrics endpoint."""

    def __init__(
        self,
        name: str,
        url: str,
        filters: Union[Mapping[str, Mapping[str, str]], Sequence[str], None],
    ) -> None:
        self.name = name  # user-defined name for the endpoint
        self.url = url  # full URL

        # - filters can be a dict {"<metric regex>": {"<label>": "<filter regex>"}}
        #   or a sequence of metric regexes. we convert the latter to a dict
        #   to make it easier to work with.
        # - the metric regexes are matched against the full metric name,
        #   i.e. "<endpoint name>.<metric name>".
        # - by default, all metrics are captured.
        self.filters = (
            filters
            if isinstance(filters, Mapping)
            else {k: {} for k in filters or [".*"]}
        )
        self.filters_tuple = _nested_dict_to_tuple(self.filters) if self.filters else ()

        self._session: Optional[requests.Session] = None
        self.samples: Deque[dict] = deque([])
        # {"<metric name>": {"<labels hash>": <index>}}
        self.label_map: Dict[str, Dict[str, int]] = defaultdict(dict)
        # {"<labels hash>": <labels>}
        self.label_hashes: Dict[str, dict] = {}

    def setup(self) -> None:
        if self._session is not None:
            return

        self._session = _setup_requests_session()

    def teardown(self) -> None:
        if self._session is None:
            return

        self._session.close()
        self._session = None

    def parse_open_metrics_endpoint(self) -> Dict[str, Union[str, int, float]]:
        assert prometheus_client_parser is not None
        assert self._session is not None

        response = self._session.get(self.url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()

        text = response.text
        measurement = {}
        for family in prometheus_client_parser.text_string_to_metric_families(text):
            if family.type not in ("counter", "gauge"):
                # todo: add support for other metric types?
                # todo: log warning about that?
                continue
            for sample in family.samples:
                name, labels, value = sample.name, sample.labels, sample.value

                if not _should_capture_metric(
                    self.name,
                    name,
                    tuple(labels.items()),
                    self.filters_tuple,
                ):
                    continue

                # md5 hash of the labels
                label_hash = hashutil._md5(str(labels).encode("utf-8")).hexdigest()
                if label_hash not in self.label_map[name]:
                    # store the index of the label hash in the label map
                    self.label_map[name][label_hash] = len(self.label_map[name])
                    # store the labels themselves
                    self.label_hashes[label_hash] = labels
                index = self.label_map[name][label_hash]
                measurement[f"{name}.{index}"] = value

        return measurement

    def sample(self) -> None:
        s = self.parse_open_metrics_endpoint()
        self.samples.append(s)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}

        prefix = f"{_PREFIX}.{self.name}."

        stats = {}
        for key in self.samples[0].keys():
            samples = [s[key] for s in self.samples if key in s]
            if samples and all(isinstance(s, (int, float)) for s in samples):
                stats[f"{prefix}{key}"] = aggregate_mean(samples)
            else:
                stats[f"{prefix}{key}"] = aggregate_last(samples)
        return stats


class OpenMetrics:
    # Poll an OpenMetrics endpoint, parse the response and return a dict of metrics
    # Implements the same Protocol interface as Asset

    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
        name: str,
        url: str,
    ) -> None:
        self.name = name
        self.url = url
        self.interface = interface
        self.settings = settings
        self.shutdown_event = shutdown_event

        self.metrics: List[Metric] = [
            OpenMetricsMetric(name, url, settings.x_stats_open_metrics_filters)
        ]

        self.metrics_monitor: MetricsMonitor = MetricsMonitor(
            asset_name=self.name,
            metrics=self.metrics,
            interface=interface,
            settings=settings,
            shutdown_event=shutdown_event,
        )

        telemetry_record = telemetry.TelemetryRecord()
        telemetry_record.feature.open_metrics = True
        interface._publish_telemetry(telemetry_record)

    @classmethod
    def is_available(cls, url: str) -> bool:
        _is_available: bool = False

        ret = prometheus_client_parser is not None
        if not ret:
            wandb.termwarn(
                "Monitoring OpenMetrics endpoints requires the `prometheus_client` package. "
                "To install it, run `pip install prometheus_client`.",
                repeat=False,
            )
            return _is_available
        # check if the endpoint is available and is a valid OpenMetrics endpoint
        _session: Optional[requests.Session] = None
        try:
            assert prometheus_client_parser is not None
            _session = _setup_requests_session()
            response = _session.get(url, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()

            # check if the response is a valid OpenMetrics response
            # text_string_to_metric_families returns a generator
            if list(
                prometheus_client_parser.text_string_to_metric_families(response.text)
            ):
                _is_available = True
        except Exception as e:
            logger.debug(
                f"OpenMetrics endpoint {url} is not available: {e}", exc_info=True
            )

        if _session is not None:
            try:
                _session.close()
            except Exception:
                pass
        return _is_available

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        # todo: also return self.label_hashes
        return {self.name: self.url}
