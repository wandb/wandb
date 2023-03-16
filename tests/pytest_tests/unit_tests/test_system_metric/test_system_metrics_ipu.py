import multiprocessing as mp
import time
from unittest import mock

import wandb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import IPU
from wandb.sdk.internal.system.assets.ipu import IPUStats
from wandb.sdk.internal.system.system_monitor import AssetInterface

CURRENT_PID = 123
OTHER_PID = 456


class MockGcIpuInfo:
    def setUpdateMode(self, update_mode: bool):  # noqa: N802
        pass

    def gcipuinfo(self):
        return self

    def getDevices(self):  # noqa: N802
        return [
            {
                "user process id": str(OTHER_PID),
                "average board temp": "20C",
                "average die temp": "25C",
                "board ipu index": "1",
                "board type": "C2",
                "clock": "1300MHz",
                "id": "0",
                "ipu power": "120W",
                "ipu utilisation": "21.25%",
                "ipu utilisation (session)": "15.65%",
            },
            {
                "user process id": str(CURRENT_PID),
                "average board temp": "30C",
                "average die temp": "39C",
                "board ipu index": "1",
                "board type": "C2",
                "clock": "1300MHz",
                "id": "1",
                "ipu power": "120W",
                "ipu utilisation": "21.25%",
                "ipu utilisation (session)": "15.65%",
            },
            {
                "average board temp": "20C",
                "average die temp": "39C",
                "board ipu index": "1",
                "board type": "C2",
                "clock": "1300MHz",
                "id": "2",
                "ipu power": "120W",
                "ipu utilisation": "21.25%",
                "ipu utilisation (session)": "15.65%",
            },
        ]


def test_profiler():
    gc_ipu_info = MockGcIpuInfo()
    ipu_profiler = IPUStats(pid=CURRENT_PID, gc_ipu_info=gc_ipu_info)

    metrics = {
        "ipu.1.user process id": CURRENT_PID,
        "ipu.1.average board temp (C)": 30,
        "ipu.1.average die temp (C)": 39,
        "ipu.1.board ipu index": 1,
        "ipu.1.clock (MHz)": 1300,
        "ipu.1.id": 1,
        "ipu.1.ipu power (W)": 120,
        "ipu.1.ipu utilisation (%)": 21.25,
        "ipu.1.ipu utilisation (session) (%)": 15.65,
    }
    ipu_profiler.sample()
    assert ipu_profiler.samples[0] == metrics

    changed_metrics = {
        "ipu.1.average board temp (C)": 30,
        "ipu.1.average die temp (C)": 39,
        "ipu.1.clock (MHz)": 1300,
        "ipu.1.ipu power (W)": 120,
        "ipu.1.ipu utilisation (%)": 21.25,
        "ipu.1.ipu utilisation (session) (%)": 15.65,
    }
    ipu_profiler.sample()
    assert ipu_profiler.samples[1] == changed_metrics


def test_ipu(test_settings):

    with mock.patch.object(
        wandb.sdk.internal.system.assets.ipu, "gcipuinfo", MockGcIpuInfo()
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

        ipu = IPU(
            interface=interface,
            settings=settings,
            shutdown_event=shutdown_event,
        )

        assert ipu.is_available()
        ipu.metrics[0]._pid = CURRENT_PID
        ipu.start()
        ipu_info = ipu.probe()["ipu"]
        devices = ipu_info.pop("devices")
        assert ipu_info == {"device_count": 3, "vendor": "Graphcore"}
        assert devices == [
            {"id": "0", "board ipu index": "1", "board type": "C2"},
            {"id": "1", "board ipu index": "1", "board type": "C2"},
            {"id": "2", "board ipu index": "1", "board type": "C2"},
        ]
        time.sleep(1)
        shutdown_event.set()
        ipu.finish()

        assert not interface.metrics_queue.empty()
