# import json
import multiprocessing as mp
import time
from unittest import mock

# import pytest
import wandb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import GPUApple
from wandb.sdk.internal.system.assets.gpu_apple import _Stats  # GPUAppleStats, _Stats
from wandb.sdk.internal.system.system_monitor import AssetInterface


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
        wandb.sdk.internal.system.assets.gpu_apple.GPUAppleStats,
        "sample",
        mock_gpu_apple_stats_sample,
    ), mock.patch.multiple(
        "wandb.sdk.internal.system.assets.gpu_apple.platform",
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
        assert gpu.probe() == {"gpuapple": {"type": "arm", "vendor": "Apple"}}
        time.sleep(1)
        shutdown_event.set()
        gpu.finish()

        assert not interface.metrics_queue.empty()


# @pytest.mark.skip(
#     reason="This test causes (?) random test suite hangs, needs investigation"
# )
# def test_gpu_apple_stats():
#     def mock_check_output(*args, **kwargs) -> str:
#         return json.dumps(
#             {"utilization": 30, "mem_used": 12, "temperature": 42.5, "power": 7.3}
#         )
#
#     with mock.patch.object(
#         wandb.sdk.system.assets.gpu_apple.subprocess,
#         "check_output",
#         mock_check_output,
#     ):
#         stats = GPUAppleStats()
#         stats.sample()
#         assert stats.samples[0] == {
#             "gpu": 30.0,
#             "memoryAllocated": 12.0,
#             "temp": 42.5,
#             "powerWatts": 7.3,
#             "powerPercent": (7.3 / stats.MAX_POWER_WATTS) * 100,
#         }
