# import multiprocessing as mp
# import time
# from unittest import mock

import pytest  # type: ignore

# import wandb
# from wandb.sdk.internal.settings_static import SettingsStatic
# from wandb.sdk.system.assets import TPU
from wandb.sdk.internal.system.assets.tpu import TPUUtilization

# from wandb.sdk.system.system_monitor import AssetInterface


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


# class MockTPUClusterResolver:
#     @staticmethod
#     def TPUClusterResolver(*args, **kwargs):  # noqa: N802
#         return MockTPUClusterResolver()
#
#     def get_master(self) -> str:
#         return "grpc://223.11.20.3:8470"


def test_tpu_instance():
    _ = pytest.importorskip(
        "tensorflow.python.distribute.cluster_resolver.tpu_cluster_resolver"
    )
    _ = pytest.importorskip("tensorflow.python.profiler.profiler_client")
    with pytest.raises(Exception) as e_info:
        TPUUtilization(service_addr="my-tpu")
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


# @pytest.mark.skip(
#     reason="This test causes (?) random test suite hangs, needs investigation"
# )
# def test_tpu(test_settings):
#
#     with mock.patch.multiple(
#         wandb.sdk.system.assets.tpu,
#         profiler_client=MockProfilerClient(),
#         tpu_cluster_resolver=MockTPUClusterResolver(),
#     ), mock.patch.dict("os.environ", {"TPU_NAME": "my-tpu"}):
#         interface = AssetInterface()
#         settings = SettingsStatic(
#             test_settings(
#                 dict(
#                     _stats_sample_rate_seconds=0.1,
#                     _stats_samples_to_average=2,
#                 )
#             ).make_static()
#         )
#         shutdown_event = mp.Event()
#
#         tpu = TPU(
#             interface=interface,
#             settings=settings,
#             shutdown_event=shutdown_event,
#         )
#
#         assert tpu.is_available()
#         tpu.start()
#         assert tpu.probe() == {"tpu": {"service_address": "223.11.20.3:8466"}}
#         time.sleep(1)
#         shutdown_event.set()
#         tpu.finish()
#
#         assert not interface.metrics_queue.empty()
#
#     assert (
#         TPU.get_service_addr(service_addr="grpc://223.11.20.3:8470")
#         == "223.11.20.3:8466"
#     )
#
#     with pytest.raises(Exception, match="Required environment variable TPU_NAME."):
#         TPU.get_service_addr()
