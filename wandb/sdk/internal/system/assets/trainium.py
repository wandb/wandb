import collections
import dataclasses
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

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


NEURON_MONITOR_DEFAULT_CONFIG: Final[dict] = {
    "period": "1s",
    "neuron_runtimes": [
        {
            "tag_filter": ".*",
            "metrics": [
                {"type": "neuroncore_counters"},
                {"type": "memory_used"},
                {"type": "neuron_runtime_vcpu_usage"},
                # {"type": "execution_stats"},
            ],
        }
    ],
    "system_metrics": [
        {"type": "vcpu_usage"},
        {"type": "memory_info"},
        {"type": "neuron_hw_counters"},
    ],
}

# todo: once a python sdk is released with the Neuron utils, rewrite this
NEURON_LS_COMMAND: Final[Tuple[str, str]] = (
    shutil.which("neuron-ls") or "/opt/aws/neuron/bin/neuron-ls",
    "-j",
)
NEURON_MONITOR_PATH: Final[str] = (
    shutil.which("neuron-monitor") or "/opt/aws/neuron/bin/neuron-monitor"
)


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
    neuroncore_utilization: Dict[int, float]  # per neuron core utilization
    host_total_memory_usage: int  # total memory usage in bytes
    neuron_device_total_memory_usage: int  # total memory usage
    host_memory_usage: _HostMemoryUsage  # host memory usage breakdown
    neuroncore_memory_usage: Dict[
        int, _NeuronCoreMemoryUsage
    ]  # per core memory usage breakdown


class NeuronCoreStats:
    """AWS Trainium stats."""

    name: str = "trn.{key}"
    samples: "Deque[_Stats]"

    def write_neuron_monitor_config(self) -> None:
        """Write neuron monitor config file."""
        # mkdir if not exists
        pathlib.Path(self.neuron_monitor_config_path).parent.mkdir(
            parents=True, exist_ok=True
        )
        # write default config
        with open(self.neuron_monitor_config_path, "w") as f:
            json.dump(NEURON_MONITOR_DEFAULT_CONFIG, f, indent=4)

    def neuron_monitor(self) -> None:
        """Run neuron-monitor in a separate process to collect raw data."""
        self.write_neuron_monitor_config()

        try:
            command = [
                NEURON_MONITOR_PATH,
                "-c",
                self.neuron_monitor_config_path,
            ]
            with subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=None,
            ) as process:
                while not self.shutdown_event.is_set():
                    if process.stdout is None:
                        self.shutdown_event.wait(0.1)
                        continue

                    raw_data = process.stdout.readline()
                    if raw_data:
                        self.raw_samples.append(raw_data)
                process.kill()
                process.wait()
        except Exception as e:
            logger.error("neuron-monitor failed: {}".format(e))

    def __init__(
        self,
        pid: int,
        neuron_monitor_config_path: Optional[str],
    ) -> None:
        self.pid = pid
        # neuron-monitor requires a config file (json)
        # we provide an option to supply a custom config file path
        # in case the default temp file path is not writable
        self.neuron_monitor_config_path = (
            neuron_monitor_config_path or tempfile.NamedTemporaryFile(delete=False).name
        )
        self.raw_samples: Deque[bytes] = deque(maxlen=10)
        self.samples: Deque[_Stats] = deque()
        self.shutdown_event = threading.Event()

        self.neuron_monitor_thread: Optional[threading.Thread] = None

    def setup(self) -> None:
        """Start the neuron-monitor thread for collecting raw data."""
        if self.neuron_monitor_thread is not None:
            return

        logger.debug("Starting neuron-monitor thread")
        self.shutdown_event.clear()
        self.neuron_monitor_thread = threading.Thread(
            name="NeuronCoreMntr",
            target=self.neuron_monitor,
            daemon=True,
        )
        self.neuron_monitor_thread.start()

    def teardown(self) -> None:
        """Stop the neuron-monitor thread."""
        logger.debug("Stopping neuron-monitor thread")
        try:
            self.shutdown_event.set()
            assert self.neuron_monitor_thread is not None
            self.neuron_monitor_thread.join()
        except Exception as e:
            logger.error("neuron-monitor thread failed to stop: {}".format(e))
        finally:
            self.neuron_monitor_thread = None

    def _is_matching_entry(self, entry: dict) -> bool:
        """Check if the entry should be saved.

        Checks if the pid in the entry matches the pid of the process.
        If not (as in the case of multi-process training with torchrun),
        checks if the LOCAL_RANK environment variable is set.

        todo: add matching by neuron_runtime_tag
        """
        return (int(entry["pid"]) == int(self.pid)) or "LOCAL_RANK" in os.environ

    def sample(self) -> None:
        try:
            raw_stats = json.loads(self.raw_samples[-1])
            neuron_runtime_data = [
                entry["report"]
                for entry in raw_stats["neuron_runtime_data"]
                if self._is_matching_entry(entry)
            ][0]  # there should be only one entry with the pid

            neuroncores_in_use = neuron_runtime_data["neuroncore_counters"][
                "neuroncores_in_use"
            ]
            # per-core utilization stats:
            neuroncore_utilization = {
                int(k): v["neuroncore_utilization"]
                for k, v in neuroncores_in_use.items()
            }
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
            host_memory_usage = _HostMemoryUsage(**usage_breakdown["host"])
            neuroncore_memory_usage = {
                int(k): _NeuronCoreMemoryUsage(**v)
                for k, v in usage_breakdown["neuroncore_memory_usage"].items()
            }

            # When the training script is executed with torchrun,
            # we only want to keep the relevant LOCAL_RANK stats
            local_rank = int(os.environ.get("LOCAL_RANK", -1337))
            if local_rank >= 0:
                neuroncore_utilization = {
                    local_rank: neuroncore_utilization[local_rank]
                }
                neuroncore_memory_usage = {
                    local_rank: neuroncore_memory_usage[local_rank]
                }

            stats: _Stats = _Stats(
                neuroncore_utilization=neuroncore_utilization,
                host_total_memory_usage=host_total_memory_usage,
                neuron_device_total_memory_usage=neuron_device_total_memory_usage,
                host_memory_usage=host_memory_usage,
                neuroncore_memory_usage=neuroncore_memory_usage,
            )
            self.samples.append(stats)

        except Exception as e:  # noqa
            pass

    def clear(self) -> None:
        self.samples.clear()

    @staticmethod
    def flatten_stats(sample: _Stats) -> dict:
        """Flatten _Stats object into a flat dict of numbers."""
        flattened = {}

        def helper(key: str, value: Any) -> None:
            if isinstance(value, (int, float)):
                ret = {f"{key}": value}
                flattened.update(ret)
                return
            elif isinstance(value, dict):
                for kk, vv in value.items():
                    if isinstance(kk, int):
                        # top-level keys are neuron core ids,
                        # so we swap the order to comply with the
                        # frontend expectations
                        helper(f"{kk}.{key}", vv)
                    else:
                        helper(f"{key}.{kk}", vv)
                return
            elif isinstance(value, list):
                for i, val in enumerate(value):
                    helper(f"{i}.{key}", val)

        for kkk, vvv in dataclasses.asdict(sample).items():
            helper(kkk, vvv)

        return flattened

    def aggregate(self) -> dict:
        if not self.samples:
            return {}

        stats = {}

        # Stats could be: numbers or dataclass objects or lists of such.
        # In the latter case that means per-core stats.
        # The dataclass objects are flat containers of numbers.

        # flatten samples and merge the corresponding values into lists
        merged_samples: Dict[str, List[Union[int, float]]] = collections.defaultdict(
            list
        )
        for flattened_sample in (self.flatten_stats(sample) for sample in self.samples):
            for k, v in flattened_sample.items():
                merged_samples[k].append(v)

        # aggregate the lists
        for k, v in merged_samples.items():
            stats[self.name.format(key=k)] = aggregate_mean(v)

        return stats


@asset_registry.register
class Trainium:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            NeuronCoreStats(
                settings._stats_pid,
                settings._stats_neuron_monitor_config_path,
            ),
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
        # todo: check if neuron-ls is available and if yes, what it reports. see:
        # https://awsdocs-neuron.readthedocs-hosted.com/en/latest/tools/neuron-sys-tools/neuron-ls.html
        if not pathlib.Path(NEURON_LS_COMMAND[0]).exists():
            return False
        # need to be extra careful as neuron tools could be pre-installed
        # on some systems that do not have the hardware
        try:
            # redirect stderr to null to avoid printing errors to the console
            # todo: alternative: check /dev/neuron0 ? sysfs support coming soon in neuron tools
            output = subprocess.check_output(
                NEURON_LS_COMMAND,
                universal_newlines=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if len(json.loads(output)) > 0:
                return True
        except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
            pass

        return False

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        try:
            self.metrics[0].check_neuron_monitor_config()  # type: ignore
            neuron_hardware_info: dict = {}
            command = [
                NEURON_MONITOR_PATH,
                "-c",
                self.metrics[0].neuron_monitor_config_path,  # type: ignore
            ]
            with subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=None,
            ) as process:
                while True:
                    if process.stdout is None:
                        time.sleep(0.1)
                        continue

                    raw_data = process.stdout.readline()
                    if raw_data:
                        parsed_data = json.loads(raw_data)
                        neuron_hardware_info = parsed_data.get(
                            "neuron_hardware_info", {}
                        )
                        neuron_hardware_info.pop("error", None)
                        break

            try:
                process.kill()
                process.wait()
            except:  # noqa
                pass

            return {self.name: neuron_hardware_info}
        except Exception as e:
            logger.error("neuron-monitor failed: {}".format(e))
            return {}
