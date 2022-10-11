import time

import pytest
import wandb
from wandb.sdk.system.system_monitor import SystemMonitor
from wandb.sdk.system.assets.tpu import TPUUtilization


class MockTPUProfiler:
    def __init__(self):
        self.utilization = 22.1

    def start(self):
        pass

    def stop(self):
        pass

    def get_tpu_utilization(self):
        return self.utilization


def test_tpu_system_stats(monkeypatch, mocked_interface, test_settings):

    monkeypatch.setattr(wandb.sdk.system.assets.tpu.TPU, "is_available", lambda: True)
    monkeypatch.setattr(
        wandb.sdk.internal.stats.tpu, "TPU", lambda: MockTPUProfiler()
    )
    stats = SystemMonitor(settings=test_settings(), interface=mocked_interface)
    # stats.start()
    # time.sleep(1)
    # stats.shutdown()
    # assert mocked_interface.record_q.queue[0].stats.item
    # record = {
    #     item.key: item.value_json
    #     for item in mocked_interface.record_q.queue[0].stats.item
    # }
    assert stats.stats()["tpu"] == MockTPUProfiler().utilization


class MockProfilerClient:
    def __init__(self, tpu_utilization: int = 10.1) -> None:
        self.tpu_utilization = tpu_utilization

    def monitor(self, service_addr, duration_ms, level):
        if service_addr != "local":
            if level == 1:
                return f"""
                Timestamp: 20:47:16
                TPU type: TPU v2
                Utilization of TPU Matrix Units (higher is better): {self.tpu_utilization}%
                """
            elif level == 2:
                return f"""
                Timestamp: 20:41:52
                TPU type: TPU v2
                Number of TPU cores: 8 (Replica count = 8, num cores per replica = 1)
                TPU idle time (lower is better): 36.9%
                Utilization of TPU Matrix Units (higher is better): {self.tpu_utilization}%
                Step time: 90.8ms (avg), 89.8ms (min), 92.2ms (max)
                Infeed percentage: 0.000% (avg), 0.000% (min), 0.000% (max)
                """
        else:
            raise Exception


def test_tpu_instance():
    _ = pytest.importorskip(
        "tensorflow.python.distribute.cluster_resolver.tpu_cluster_resolver"
    )
    _ = pytest.importorskip("tensorflow.python.profiler.profiler_client")
    with pytest.raises(Exception) as e_info:
        tpu_profiler = TPUUtilization(tpu="my-tpu")
        assert "Failed to find TPU. Try specifying TPU zone " in str(e_info.value)

    tpu_profiler = TPUUtilization(service_addr="local")
    tpu_profiler._profiler_client = MockProfilerClient()
    # For TPU local (i.e. TPU_VM), TF doesn't support monitoring.
    with pytest.raises(Exception) as e_info:
        tpu_profiler.sample()
    assert len(tpu_profiler.samples) == 0

    tpu_profiler = TPUUtilization(service_addr="my-tpu")
    tpu_profiler._profiler_client = MockProfilerClient()
    tpu_profiler.sample()
    assert len(tpu_profiler.samples) == 1
    assert tpu_profiler.samples[0] == 10.1
