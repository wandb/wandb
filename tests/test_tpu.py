def mock_monitor(service_addr, duration_ms, level=1):
    if service_addr != "":
        if level == 1:
            return f"""
            Timestamp: 20:47:16
            TPU type: TPU v2
            Utilization of TPU Matrix Units (higher is better): 10%
            """
        elif level == 2:
            return f"""
            Timestamp: 20:41:52
            TPU type: TPU v2
            Number of TPU cores: 8 (Replica count = 8, num cores per replica = 1)
            TPU idle time (lower is better): 36.9%
            Utilization of TPU Matrix Units (higher is better): 10%
            Step time: 90.8ms (avg), 89.8ms (min), 92.2ms (max)
            Infeed percentage: 0.000% (avg), 0.000% (min), 0.000% (max)
            """
    else:
        raise Exception


import time
from unittest.mock import Mock

import wandb
from wandb.sdk.internal.stats import SystemStats


class MockTPUProfiler(object):
    def __init__(self):
        self.utilization = 10

    def start(self):
        pass

    def stop(self):
        pass

    def get_tpu_utilization(self):
        return self.utilization


def test_tpu_system_stats(monkeypatch):
    mock_interface = Mock()
    monkeypatch.setattr(wandb.sdk.internal.stats.tpu, "is_tpu_available", lambda: True)
    monkeypatch.setattr(
        wandb.sdk.internal.stats.tpu, "get_profiler", lambda: MockTPUProfiler()
    )
    stats = SystemStats(pid=1000, interface=mock_interface)
    stats.start()
    time.sleep(1)
    samples = stats.sampler
    stats.shutdown()

    assert "tpu" in samples and MockTPUProfiler().utilization in samples["tpu"]
