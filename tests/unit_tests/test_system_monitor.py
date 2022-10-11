from collections import deque
import multiprocessing as mp
import time
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
import wandb
from wandb.sdk.system.assets.asset_registry import asset_registry
from wandb.sdk.system.assets import CPU, Disk, Memory, GPU, GPUApple, IPU, Network, TPU
from wandb.sdk.system.assets.interfaces import MetricsMonitor, MetricType
from wandb.sdk.internal.settings_static import SettingsStatic

from wandb.sdk.system.system_monitor import AssetInterface, SystemMonitor


if TYPE_CHECKING:
    from typing import Deque


class MockMetric:
    name: str = "mock_metric"
    # at first, we will only support the gauge type
    metric_type: MetricType = "gauge"
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

    def serialize(self) -> dict:
        return {self.name: self.samples[0]}


class MockAsset1:
    def __init__(self, interface, settings, shutdown_event) -> None:
        self.metrics = [
            MockMetric(name="mock_metric_1", value=42),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.metrics, interface, settings, shutdown_event
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
        self.metrics = [
            MockMetric(name="mock_metric_2", value=24),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.metrics, interface, settings, shutdown_event
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
    metric_type: MetricType = "gauge"
    samples: "Deque[Any]" = deque()

    def sample(self) -> None:
        raise Exception("MockBrokenMetric failed to sample")

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        if self.samples:
            return {self.name: self.samples[0]}
        return {}


def test_asset_registry():
    registry = asset_registry._registry
    assert len(registry) == 8
    for asset in (CPU, Disk, Memory, GPU, GPUApple, IPU, Network, TPU):
        assert asset in registry


def test_metrics_monitor(capsys, test_settings):
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
        ).make_static()
    )
    shutdown_event = mp.Event()

    metrics_monitor = MetricsMonitor(
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

    _, err = capsys.readouterr()
    assert "Failed to sample metric: MockBrokenMetric failed to sample" in err


@pytest.mark.parametrize(
    "join_assets,num_keys",
    [(True, 2), (False, 1)],
)
def test_system_monitor(capsys, test_settings, join_assets, num_keys):
    interface = AssetInterface()
    settings = SettingsStatic(
        test_settings(
            dict(
                _stats_sample_rate_seconds=0.1,
                _stats_samples_to_average=2,
                _stats_join_assets=join_assets,
            )
        ).make_static()
    )

    # todo: refactor this ugliness into a factory
    mock_assets = [MockAsset1, MockAsset2]

    with mock.patch.object(
        wandb.sdk.system.assets.asset_registry,
        "_registry",
        mock_assets,
    ):
        system_monitor = SystemMonitor(
            interface=interface,
            settings=settings,
        )
        system_monitor.start()
        time.sleep(1)
        system_monitor.finish()

    while not interface.metrics_queue.empty():
        metric_record = interface.metrics_queue.get()
        assert len(metric_record) == num_keys
