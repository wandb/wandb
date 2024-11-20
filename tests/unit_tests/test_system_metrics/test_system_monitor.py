import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import (
    CPU,
    GPU,
    GPUAMD,
    IPU,
    TPU,
    Disk,
    Memory,
    Network,
    Trainium,
)
from wandb.sdk.internal.system.assets.asset_registry import asset_registry
from wandb.sdk.internal.system.assets.interfaces import MetricsMonitor
from wandb.sdk.internal.system.system_monitor import AssetInterface

if TYPE_CHECKING:
    from typing import Deque


class MockMetric:
    name: str = "mock_metric"
    # at first, we will only support the gauge type
    samples: "Deque[Any]" = deque()

    def __init__(self, **kwargs):
        name = kwargs.pop("name", None)
        if name:
            self.name = name
        self.default_value = kwargs.pop("value", 42)

    def sample(self) -> None:
        self.samples.append(self.default_value)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if self.samples:
            return {self.name: self.samples[-1]}
        return {}


class MockAsset1:
    def __init__(self, interface, settings, shutdown_event) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics = [
            MockMetric(name="mock_metric_1", value=42),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.name, self.metrics, interface, settings, shutdown_event
        )

    @classmethod
    def is_available(cls) -> bool:
        return True

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        pass


class MockAsset2:
    def __init__(self, interface, settings, shutdown_event) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics = [
            MockMetric(name="mock_metric_2", value=24),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.name, self.metrics, interface, settings, shutdown_event
        )

    @classmethod
    def is_available(cls) -> bool:
        return True

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        pass


class MockBrokenMetric:
    name: str = "mock_broken_metric"
    # at first, we will only support the gauge type
    samples: "Deque[Any]" = deque()

    def sample(self) -> None:
        raise Exception("MockBrokenMetric failed to sample")

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if self.samples:
            return {self.name: self.samples[0]}
        return {}


def test_asset_registry():
    # test that the asset registry is populated with the correct assets
    # should be updated if new assets are added
    registry = asset_registry._registry
    assert len(registry) == 9
    for asset in (
        CPU,
        Disk,
        Memory,
        GPU,
        GPUAMD,
        IPU,
        Network,
        TPU,
        Trainium,
    ):
        assert asset in registry


def test_metrics_monitor(capsys, test_settings):
    # test that the metrics monitor is able to robustly sample metrics
    mock_metric = MockMetric()
    mock_broken_metric = MockBrokenMetric()
    metrics = [mock_metric, mock_broken_metric]
    interface = AssetInterface()
    settings = SettingsStatic(
        test_settings(
            dict(
                _stats_sample_rate_seconds=0.1,
                _stats_samples_to_average=2,
            )
        ).to_proto()
    )
    shutdown_event = threading.Event()

    metrics_monitor = MetricsMonitor(
        asset_name="test_metrics_monitor",
        metrics=metrics,
        interface=interface,
        settings=settings,
        shutdown_event=shutdown_event,
    )
    metrics_monitor.start()
    time.sleep(1)
    shutdown_event.set()
    metrics_monitor.finish()

    while not interface.metrics_queue.empty():
        metric_record = interface.metrics_queue.get()
        assert metric_record == {mock_metric.name: 42}

    assert len(mock_metric.samples) == 0
