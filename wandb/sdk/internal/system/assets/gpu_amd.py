import json
import logging
import shutil
import subprocess
import sys
import threading
from collections import deque
from typing import TYPE_CHECKING, Any, Dict, List, TypedDict

if sys.version_info >= (3, 8):
    from typing import Final
else:
    from typing_extensions import Final

from wandb.sdk.lib import telemetry

from .aggregators import aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic


logger = logging.getLogger(__name__)


ROCM_SMI_CMD: Final[str] = shutil.which("rocm-smi") or "/usr/bin/rocm-smi"


def get_rocm_smi_stats() -> Dict[str, Any]:
    command = [str(ROCM_SMI_CMD), "-a", "--json"]
    output = (
        subprocess.check_output(command, universal_newlines=True).strip().split("\n")
    )[0]
    return json.loads(output)


class _Stats(TypedDict):
    gpu: float
    memoryAllocated: float  # noqa: N815
    temp: float
    powerWatts: float  # noqa: N815
    powerPercent: float  # noqa: N815


class GPUAMDStats:
    """Stats for AMD GPU devices."""

    name = "gpu.{gpu_id}.{key}"
    samples: "Deque[_Stats]"

    def __init__(self) -> None:
        self.samples = deque()

    def sample(self) -> None:
        try:
            raw_stats = get_rocm_smi_stats()

            stats: _Stats = {
                "gpu": raw_stats["utilization"],
                "memoryAllocated": raw_stats["mem_used"],
                "temp": raw_stats["temperature"],
                "powerWatts": raw_stats["power"],
                "powerPercent": 100,
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
class GPUAMD:
    """GPUAMD is a class for monitoring AMD GPU devices.

    Uses AMD's rocm_smi tool to get GPU stats.
    For the list of supported environments and devices, see
    https://github.com/RadeonOpenCompute/ROCm/blob/develop/docs/deploy/
    """

    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            GPUAMDStats(),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )
        telemetry_record = telemetry.TelemetryRecord()
        telemetry_record.env.amd_gpu = True
        interface._publish_telemetry(telemetry_record)

    @classmethod
    def is_available(cls) -> bool:
        try:
            rocm_smi_available = shutil.which(ROCM_SMI_CMD) is not None
            if rocm_smi_available:
                _ = get_rocm_smi_stats()
                return True
        except Exception:
            pass
        return False

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        return {}
