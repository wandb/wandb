import json
import logging
import pathlib
import platform
import subprocess
import sys
import threading
from collections import deque
from typing import TYPE_CHECKING, List

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

from wandb.sdk.lib import telemetry

from .aggregators import aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic


logger = logging.getLogger(__name__)


class _Stats(TypedDict):
    gpu: float
    memoryAllocated: float  # noqa: N815
    temp: float
    powerWatts: float  # noqa: N815
    powerPercent: float  # noqa: N815
    # cpuWaitMs: float


class GPUAppleStats:
    """Apple GPU stats available on Arm Macs."""

    name = "gpu.0.{}"
    samples: "Deque[_Stats]"

    # TODO: hard coded max watts as 16.5, found this number in the SMC list.
    #  Eventually we can have the apple_gpu_stats binary query for this.
    MAX_POWER_WATTS = 16.5

    def __init__(self) -> None:
        self.samples = deque()
        self.binary_path = (
            pathlib.Path(sys.modules["wandb"].__path__[0]) / "bin" / "apple_gpu_stats"
        ).resolve()

    def sample(self) -> None:
        try:
            command = [str(self.binary_path), "--json"]
            output = (
                subprocess.check_output(command, universal_newlines=True)
                .strip()
                .split("\n")
            )[0]
            raw_stats = json.loads(output)

            stats: _Stats = {
                "gpu": raw_stats["utilization"],
                "memoryAllocated": raw_stats["mem_used"],
                "temp": raw_stats["temperature"],
                "powerWatts": raw_stats["power"],
                "powerPercent": (raw_stats["power"] / self.MAX_POWER_WATTS) * 100,
                # TODO: this stat could be useful eventually, it was consistently
                #  0 in my experimentation and requires a frontend change
                #  so leaving it out for now.
                # "cpuWaitMs": raw_stats["cpu_wait_ms"],
            }

            self.samples.append(stats)

        except (OSError, ValueError, TypeError, subprocess.CalledProcessError) as e:
            logger.exception(f"GPU stats error: {e}")

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        stats = {}
        for key in self.samples[0].keys():
            samples = [s[key] for s in self.samples]  # type: ignore
            aggregate = aggregate_mean(samples)
            stats[self.name.format(key)] = aggregate
        return stats


@asset_registry.register
class GPUApple:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            GPUAppleStats(),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )
        telemetry_record = telemetry.TelemetryRecord()
        telemetry_record.env.m1_gpu = True
        interface._publish_telemetry(telemetry_record)

    @classmethod
    def is_available(cls) -> bool:
        return platform.system() == "Darwin" and platform.processor() == "arm"

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        # todo: make this actually meaningful
        return {self.name: {"type": "arm", "vendor": "Apple"}}
