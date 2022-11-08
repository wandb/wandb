import multiprocessing as mp
import time
from collections import deque
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
import wandb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import (
    CPU,
    GPU,
    IPU,
    TPU,
    Disk,
    GPUApple,
    Memory,
    Network,
)
from wandb.sdk.internal.system.assets.asset_registry import asset_registry
from wandb.sdk.internal.system.assets.interfaces import MetricsMonitor
from wandb.sdk.internal.system.system_monitor import AssetInterface, SystemMonitor

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
    assert len(registry) == 8
    for asset in (CPU, Disk, Memory, GPU, GPUApple, IPU, Network, TPU):
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
        ).make_static()
    )
    shutdown_event = mp.Event()

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

    _, err = capsys.readouterr()
    assert "Failed to sample metric: MockBrokenMetric failed to sample" in err


@pytest.mark.parametrize(
    "join_assets,num_keys",
    [(True, 2), (False, 1)],
)
def test_system_monitor(test_settings, join_assets, num_keys):
    # - test compatibility mode where we join metrics from individual assets
    #   before publishing them to the interface
    # - test the future default mode where we publish metrics from individual assets
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
        wandb.sdk.internal.system.assets.asset_registry,
        "_registry",
        mock_assets,
    ):
        system_monitor = SystemMonitor(
            interface=interface,
            settings=settings,
        )
        system_monitor.start()
        time.sleep(1.5)
        system_monitor.finish()

    max_num_keys = 0
    while not interface.metrics_queue.empty():
        metric_record = interface.metrics_queue.get()
        # it's tricky to get the timing right, so we are looking at the
        # maximum number of keys we've seen in the queue as it should be == num_keys;
        # sometimes, due to timing we might see less than num_keys
        max_num_keys = max(max_num_keys, len(metric_record))
    assert max_num_keys == num_keys
