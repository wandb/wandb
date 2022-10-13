import multiprocessing as mp
import time
from unittest import mock

import wandb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.system.assets import GPUApple
from wandb.sdk.system.assets.gpu_apple import _Stats
from wandb.sdk.system.system_monitor import AssetInterface


def mock_gpu_apple_stats_sample(self) -> None:
    stats: _Stats = {
        "gpu": 30.0,
        "memoryAllocated": 12.0,
        "temp": 42.5,
        "powerWatts": 7.3,
        "powerPercent": (7.3 / self.MAX_POWER_WATTS) * 100,
    }
    self.samples.append(stats)


def test_gpu_apple(test_settings):

    with mock.patch.object(
        wandb.sdk.system.assets.gpu_apple.GPUAppleStats,
        "sample",
        mock_gpu_apple_stats_sample,
    ), mock.patch.multiple(
        "wandb.sdk.system.assets.gpu_apple.platform",
        system=lambda: "Darwin",
        processor=lambda: "arm",
    ):
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

        gpu = GPUApple(
            interface=interface,
            settings=settings,
            shutdown_event=shutdown_event,
        )
        assert gpu.is_available()
        gpu.start()
        time.sleep(1)
        shutdown_event.set()
        gpu.finish()

        assert not interface.metrics_queue.empty()
