import json
import logging
import multiprocessing as mp
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


# NEURON_LS_COMMAND = ["neuron-ls"]
# NEURON_MONITOR_COMMAND = ["neuron-monitor", "-c", "neuron_monitor_config.json"]
# fixme:
NEURON_LS_COMMAND = ["ls", "-lhtr"]
NEURON_MONITOR_COMMAND = ["/Users/dimaduev/dev/client/time"]


class _NeuronCoreMemoryUsage(TypedDict):
    constants: int
    model_code: int
    model_shared_scratchpad: int
    runtime_memory: int
    tensors: int


class _Stats(TypedDict):
    neuroncore_utilization: List[float]
    neuroncore_memory_usage: List[_NeuronCoreMemoryUsage]


class NeuronCoreStats:
    """
    AWS Trainium stats per Neuron Core.
    """

    name = "trn.{i}.{}"
    samples: "Deque[_Stats]"

    def neuron_monitor(self):
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

    def __init__(self) -> None:
        self.raw_samples = deque(maxlen=10)
        self.samples = deque()
        self.shutdown_event = threading.Event()

        self.neuron_monitor_thread = threading.Thread(
            name="NeuronCoreMntr",
            target=self.neuron_monitor,
            daemon=True,
        )
        self.neuron_monitor_thread.start()

    def sample(self) -> None:
        try:
            raw_stats = json.loads(self.raw_samples[-1])
            print(raw_stats)
            # stats: _Stats = ...
            #
            # self.samples.append(stats)

        except Exception as e:
            logger.exception(f"Neuron core stats error: {e}")

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        stats = {}
        if self.samples:
            for key in self.samples[0].keys():
                samples = [s[key] for s in self.samples]  # type: ignore
                aggregate = aggregate_mean(samples)
                stats[self.name.format(key)] = aggregate
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
            NeuronCoreStats(),
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
                print("*** shutting down", metric.name)
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
