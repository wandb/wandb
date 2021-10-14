import pytest
import time

import wandb
from wandb.sdk.internal.stats import SystemStats
from wandb.sdk.internal.tpu import TPUProfiler


class MockTPUProfiler(object):
    def __init__(self):
        self.utilization = 22.1

    def start(self):
        pass

    def stop(self):
        pass

    def get_tpu_utilization(self):
        return self.utilization


def test_tpu_system_stats(monkeypatch, fake_interface):

    monkeypatch.setattr(wandb.sdk.internal.stats.tpu, "is_tpu_available", lambda: True)
    monkeypatch.setattr(
        wandb.sdk.internal.stats.tpu, "get_profiler", lambda: MockTPUProfiler()
    )
    stats = SystemStats(pid=1000, interface=fake_interface)
    stats.start()
    time.sleep(1)
    stats.shutdown()
    assert fake_interface.record_q.queue[0].stats.item
    record = {
        item.key: item.value_json
        for item in fake_interface.record_q.queue[0].stats.item
    }
    assert float(record["tpu"]) == MockTPUProfiler().utilization


def check_tf_packages():
    try:
        from tensorflow.python.distribute.cluster_resolver import tpu_cluster_resolver
        from tensorflow.python.profiler import profiler_client
    except (ImportError):
        return False
    return True


@pytest.mark.skipif(
    check_tf_packages,
    reason="tensorflow modules tpu_cluster_resolver and profiler_client are missing",
)
def test_tpu_instance():
    with pytest.raises(Exception) as e_info:
        TPUProfiler()
    assert "Failed to find TPU. Try specifying TPU zone " in str(e_info.value)
