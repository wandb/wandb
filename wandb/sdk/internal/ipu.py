import logging
from typing import Any, Dict, Optional, Set, Tuple, Union


logger = logging.getLogger(__name__)

# The metrics that change over time.
# Only these are returned on each invocation
# to avoid sending a load of unnecessary data.
variable_metric_keys = {
    "average board temp",
    "average die temp",
    "clock",
    "ipu power",
    "ipu utilisation",
    "ipu utilisation (session)",
}


class IPUProfiler:
    def __init__(self, pid: int, gc_ipu_info: Any = None):
        if gc_ipu_info is None:
            import gcipuinfo  # type: ignore

            self._gc_ipu_info = gcipuinfo.gcipuinfo()
        else:
            self._gc_ipu_info = gc_ipu_info
        self._gc_ipu_info.setUpdateMode(True)

        self._pid = pid
        self._devices_called: Set[str] = set()

    def get_metrics(self) -> Dict[str, Union[int, float]]:
        metrics = {}
        devices = self._gc_ipu_info.getDevices()
        for device in devices:
            device_metrics: Dict[str, str] = dict(device)

            pid = device_metrics.get("user process id")
            if pid is None or int(pid) != self._pid:
                continue

            device_id = device_metrics.get("id")
            initial_call = device_id not in self._devices_called
            if device_id is not None:
                self._devices_called.add(device_id)

            for key, value in device_metrics.items():
                log_metric = initial_call or key in variable_metric_keys
                if not log_metric:
                    continue
                parsed = self.parse_metric(key, value)
                if parsed is None:
                    continue
                parsed_key, parsed_value = parsed
                metrics[f"ipu.{device_id}.{parsed_key}"] = parsed_value
        return metrics

    def parse_metric(
        self, key: str, value: str
    ) -> Optional[Tuple[str, Union[int, float]]]:
        metric_suffixes = {
            "temp": "C",
            "clock": "MHz",
            "power": "W",
            "utilisation": "%",
            "utilisation (session)": "%",
            "speed": "GT/s",
        }

        for metric, suffix in metric_suffixes.items():
            if key.endswith(metric) and value.endswith(suffix):
                value = value[: -len(suffix)]
                key = f"{key} ({suffix})"

        try:
            float_value = float(value)
            num_value = int(float_value) if float_value.is_integer() else float_value
        except ValueError:
            return None

        return key, num_value


def is_ipu_available() -> bool:
    try:
        import gcipuinfo  # noqa
    except ImportError:
        return False

    return True
