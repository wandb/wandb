import multiprocessing as mp
import time
from typing import Tuple
from unittest import mock

import wandb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import GPU
from wandb.sdk.internal.system.system_monitor import AssetInterface


class MockPynvml:
    NVMLError = Exception
    NVML_TEMPERATURE_GPU = 10

    def nvmlInit(self) -> bool:  # noqa: N802
        return True

    def nvmlDeviceGetCount(self) -> int:  # noqa: N802
        return 1

    def nvmlDeviceGetName(self, handle: int) -> str:  # noqa: N802
        return "Mock GPU"

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:  # noqa: N802
        return 0

    def nvmlDeviceGetMemoryInfo(self, handle: int):  # noqa: N802
        info = mock.MagicMock()
        info.used = 24
        info.total = 42
        return info

    def nvmlDeviceGetComputeRunningProcesses(  # noqa: N802
        self, handle: int
    ) -> Tuple[int, ...]:
        return -1, -2, -3

    def nvmlDeviceGetGraphicsRunningProcesses(  # noqa: N802
        self, handle: int
    ) -> Tuple[int, ...]:
        return -1, -2, -3

    #
    def nvmlDeviceGetUtilizationRates(self, handle: int):  # noqa: N802
        rates = mock.MagicMock(bound_method=float)
        rates.memory = 42.0
        rates.gpu = 24.0
        return rates

    def nvmlDeviceGetTemperature(  # noqa: N802
        self, handle: int, sensor_type: int
    ) -> float:
        return 420.0

    def nvmlDeviceGetPowerUsage(self, handle: int):  # noqa: N802
        return 40.5

    #
    def nvmlDeviceGetEnforcedPowerLimit(self, handle: int):  # noqa: N802
        return 42


def test_gpu(test_settings):
    mock_pynvml = MockPynvml()

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

    gpu = GPU(
        interface=interface,
        settings=settings,
        shutdown_event=shutdown_event,
    )

    with mock.patch.object(
        wandb.sdk.internal.system.assets.gpu,
        "pynvml",
        mock_pynvml,
    ), mock.patch.object(
        wandb.sdk.internal.system.assets.gpu,
        "gpu_in_use_by_this_process",
        lambda *_: True,
    ):

        assert gpu.is_available()
        gpu.start()
        assert gpu.probe() == {
            "gpu": "Mock GPU",
            "gpu_count": 1,
            "gpu_devices": [{"name": "Mock GPU", "memory_total": 42}],
        }
        time.sleep(1)
        shutdown_event.set()
        gpu.finish()

        assert not interface.metrics_queue.empty()

    assert gpu.probe() == {}
