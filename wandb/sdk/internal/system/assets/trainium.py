import dataclasses
import json
import logging
import multiprocessing as mp
import pathlib
import subprocess
import sys
import threading
from collections import deque
from typing import TYPE_CHECKING, Any, List

from wandb.sdk.lib import telemetry

from .aggregators import aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic


logger = logging.getLogger(__name__)


neuron_monitor_config = {
    "period": "1s",
    "neuron_runtimes": [
        {
            "tag_filter": ".*",
            "metrics": [
                {"type": "neuroncore_counters"},
                {"type": "memory_used"},
                {"type": "neuron_runtime_vcpu_usage"},
                {"type": "execution_stats"},
            ],
        }
    ],
    "system_metrics": [
        {"type": "vcpu_usage"},
        {"type": "memory_info"},
        {"type": "neuron_hw_counters"},
    ],
}


# NEURON_LS_COMMAND = ["neuron-ls"]
# NEURON_MONITOR_CONFIG = pathlib.Path(__file__).parent / "neuron_monitor_config.json"
# NEURON_MONITOR_COMMAND = ["neuron-monitor", "-c", str(NEURON_MONITOR_CONFIG)]
# fixme:
NEURON_LS_COMMAND = ["ls", "-lhtr", "/"]
NEURON_MONITOR_COMMAND = ["/Users/dimaduev/dev/client/time"]


@dataclasses.dataclass
class _NeuronCoreMemoryUsage:
    constants: int
    model_code: int
    model_shared_scratchpad: int
    runtime_memory: int
    tensors: int


@dataclasses.dataclass
class _HostMemoryUsage:
    application_memory: int
    constants: int
    dma_buffers: int
    tensors: int


@dataclasses.dataclass
class _Stats:
    neuroncore_utilization: List[float]  # per neuron core utilization
    host_total_memory_usage: int  # total memory usage in bytes
    neuron_device_total_memory_usage: int  # total memory usage
    host_memory_usage: _HostMemoryUsage  # host memory usage breakdown
    neuroncore_memory_usage: List[
        _NeuronCoreMemoryUsage
    ]  # per core memory usage breakdown


class NeuronCoreStats:
    """
    AWS Trainium stats per Neuron Core.
    """

    name: str = "trn.{key}"
    samples: "Deque[_Stats]"

    def neuron_monitor(self) -> None:
        popen = subprocess.Popen(
            NEURON_MONITOR_COMMAND,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=None,
        )
        while not self.shutdown_event.is_set():
            if popen.stdout is None:
                continue

            raw_data = popen.stdout.readline()
            if raw_data:
                self.raw_samples.append(raw_data)

    def __init__(self, pid: int) -> None:
        # self.pid = pid
        self.pid = 16851  # fixme
        self.raw_samples: "Deque[bytes]" = deque(maxlen=10)
        self.samples: "Deque[_Stats]" = deque()
        self.shutdown_event = threading.Event()

        self.neuron_monitor_thread = threading.Thread(
            name="NeuronCoreMntr",
            target=self.neuron_monitor,
            daemon=True,
        )
        self.neuron_monitor_thread.start()

    def sample(self) -> None:
        try:
            raw_stats = json.loads(self.raw_samples[-1])  # type: ignore
            # if "neuron_runtime_data" not in raw_stats:
            #     return None
            neuron_runtime_data = [
                entry["report"]
                for entry in raw_stats["neuron_runtime_data"]
                if entry["pid"] == self.pid
            ][
                0
            ]  # there should be only one entry with the pid

            neuroncores_in_use = neuron_runtime_data["neuroncore_counters"][
                "neuroncores_in_use"
            ]
            # per-core utilization stats:
            neuroncore_utilization = [
                v["neuroncore_utilization"] for k, v in neuroncores_in_use.items()
            ]
            # memory usage
            neuron_runtime_used_bytes = neuron_runtime_data["memory_used"][
                "neuron_runtime_used_bytes"
            ]
            # memory usage totals
            host_total_memory_usage = neuron_runtime_used_bytes["host"]
            neuron_device_total_memory_usage = neuron_runtime_used_bytes[
                "neuron_device"
            ]
            # memory usage breakdown
            usage_breakdown = neuron_runtime_used_bytes["usage_breakdown"]
            host_memory_usage = _HostMemoryUsage(**usage_breakdown["host"])  # type: ignore
            neuroncore_memory_usage = [
                _NeuronCoreMemoryUsage(**v)  # type: ignore
                for v in usage_breakdown["neuroncore_memory_usage"].values()
            ]

            stats: _Stats = _Stats(
                neuroncore_utilization=neuroncore_utilization,
                host_total_memory_usage=host_total_memory_usage,
                neuron_device_total_memory_usage=neuron_device_total_memory_usage,
                host_memory_usage=host_memory_usage,
                neuroncore_memory_usage=neuroncore_memory_usage,
            )
            self.samples.append(stats)

        except Exception as e:  # noqa
            # logger.exception(f"Neuron core stats error: {e}")
            # import traceback
            # print(traceback.format_exc())
            pass

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}

        stats = {}

        n_neuroncores = len(self.samples[-1].neuroncore_utilization)

        # Stats could be: numbers or dataclass objects or lists of such.
        # In the latter case that means per-core stats.
        # The dataclass objects are flat containers of numbers.

        # aggregate totals. parse stats based on the structure described above

        for field in dataclasses.fields(_Stats):
            key = field.name
            # last collected sample
            _value = getattr(self.samples[-1], key)
            print(f"key: {key}, value: {_value}")

            if isinstance(_value, (int, float)):
                # global number stats
                stats[self.name.format(key=key)] = aggregate_mean(
                    [getattr(s, key) for s in self.samples]
                )
            elif isinstance(_value, list):
                # per-core stats
                if isinstance(_value[0], (int, float)):
                    # list of numbers
                    for i in range(n_neuroncores):
                        stats[self.name.format(key=f"{i}.{key}")] = aggregate_mean(
                            [s.neuroncore_utilization[i] for s in self.samples]
                        )
                else:
                    # list of dataclass objects
                    for subfield in dataclasses.fields(type(_value[0])):
                        subkey = subfield.name
                        for i in range(n_neuroncores):
                            stats[
                                self.name.format(key=f"{i}.{key}.{subkey}")
                            ] = aggregate_mean(
                                [
                                    getattr(getattr(s, key)[i], subkey)
                                    for s in self.samples
                                ]
                            )
            else:
                # dataclass object
                for subfield in dataclasses.fields(field.type):
                    subkey = subfield.name
                    stats[self.name.format(key=f"{key}.{subkey}")] = aggregate_mean(
                        [getattr(getattr(s, key), subkey) for s in self.samples]
                    )

        # keys_totals = (
        #     "host_total_memory_usage",
        #     "neuron_device_total_memory_usage",
        # )
        # for key in keys_totals:
        #     stats[self.base_name.format(key=key)] = aggregate_mean(
        #         [getattr(s, key) for s in self.samples]
        #     )
        # # aggregate neuroncore utilization
        # for i in range(n_neuroncores):
        #     stats[self.name.format(i=i, key="neuroncore_utilization")] = aggregate_mean(
        #         [s.neuroncore_utilization[i] for s in self.samples]
        #     )
        #
        # # aggregate host memory usage breakdown
        # keys_host_memory_usage = (
        #     field.name for field in dataclasses.fields(_HostMemoryUsage)
        # )
        # for key in keys_host_memory_usage:
        #     stats[
        #         self.base_name.format(key=f"host_memory_usage.{key}")
        #     ] = aggregate_mean(
        #         [getattr(s.host_memory_usage, key) for s in self.samples]
        #     )
        #
        # # aggregate per-core memory usage stats
        # keys_neuroncore_memory_usage = (
        #     field.name for field in dataclasses.fields(_NeuronCoreMemoryUsage)
        # )
        # for key in keys_neuroncore_memory_usage:
        #     for i in range(n_neuroncores):
        #         stats[
        #             self.name.format(i=i, key=f"neuroncore_memory_usage.{key}")
        #         ] = aggregate_mean(
        #             [getattr(s.neuroncore_memory_usage[i], key) for s in self.samples]
        #         )

        print(stats)

        return stats


@asset_registry.register
class Trainium:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: mp.synchronize.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            NeuronCoreStats(settings._stats_pid),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )
        telemetry_record = telemetry.TelemetryRecord()
        telemetry_record.env.trainium = True
        interface._publish_telemetry(telemetry_record)

    @classmethod
    def is_available(cls) -> bool:
        # check if neuron-ls is available and if yes, what it reports. see:
        # https://awsdocs-neuron.readthedocs-hosted.com/en/latest/tools/neuron-sys-tools/neuron-ls.html
        try:
            output = (
                subprocess.check_output(NEURON_LS_COMMAND, universal_newlines=True)
                .strip()
                .split("\n")
            )
            if len(output) > 4:  # header is 4 lines
                return True
        except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
            pass
        return False

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()
        # stop the raw data acquisition threads
        for metric in self.metrics:
            if hasattr(metric, "shutdown_event"):
                logger.debug("Stopping neuron-monitor thread")
                metric.shutdown_event.set()

    def probe(self) -> dict:
        neuron_hardware_info: dict = {}
        popen = subprocess.Popen(
            NEURON_MONITOR_COMMAND,
            stdout=subprocess.PIPE,
            stderr=None,
        )
        while True:
            if popen.stdout is None:
                continue

            raw_data = popen.stdout.readline()
            if raw_data:
                parsed_data = json.loads(raw_data)
                neuron_hardware_info = parsed_data.get("neuron_hardware_info", {})
                neuron_hardware_info.pop("error", None)
                break

        popen.terminate()

        return {self.name: neuron_hardware_info}
