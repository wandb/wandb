import time

import pytest
import wandb
from wandb.sdk.internal.stats import SystemStats
from wandb.sdk.internal.tpu import TPUProfiler


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

    monkeypatch.setattr(wandb.sdk.internal.stats.tpu, "is_tpu_available", lambda: True)
    monkeypatch.setattr(
        wandb.sdk.internal.stats.tpu, "get_profiler", lambda: MockTPUProfiler()
    )
    stats = SystemStats(settings=test_settings(), interface=mocked_interface)
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
        tpu_profiler = TPUProfiler(tpu="my-tpu")
        assert "Failed to find TPU. Try specifying TPU zone " in str(e_info.value)

    tpu_profiler = TPUProfiler(service_addr="local")
    tpu_profiler._profiler_client = MockProfilerClient()
    time.sleep(1)
    tpu_profiler.stop()

    # For TPU local (i.e. TPU_VM), TF doesn't support monitoring. Hence to avoid reporting 0%,
    # we return `None` instead for the utilization and filter out before sending to the backend
    assert tpu_profiler.get_tpu_utilization() is None
