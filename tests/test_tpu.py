import pytest
from unittest.mock import patch
import wandb


class MockTPUProfiler(object):
    def __init__(self):
        self.utilization = 10

    def start(self):
        pass

    def stop(self):
        pass

    def get_tpu_utilization(self):
        return self.utilization


# def mock_monitor(service_addr, duration_ms, level=1):
#     if service_addr != "":
#         if level == 1:
#             return f"""
#             Timestamp: 20:47:16
#             TPU type: TPU v2
#             Utilization of TPU Matrix Units (higher is better): 10%
#             """
#         elif level == 2:
#             return f"""
#             Timestamp: 20:41:52
#             TPU type: TPU v2
#             Number of TPU cores: 8 (Replica count = 8, num cores per replica = 1)
#             TPU idle time (lower is better): 36.9%
#             Utilization of TPU Matrix Units (higher is better): 10%
#             Step time: 90.8ms (avg), 89.8ms (min), 92.2ms (max)
#             Infeed percentage: 0.000% (avg), 0.000% (min), 0.000% (max)
#             """
#     else:
#         raise Exception


@pytest.mark.parametrize("tpu_name", ["my-tpu"])
def test_tpu_stats(
    tpu_name, monkeypatch, test_settings, live_mock_server, parse_ctx, capsys
):

    monkeypatch.setenv("TPU_NAME", tpu_name)

    # with patch(
    #     "wandb.sdk.internal.tpu.tpu_cluster_resolver"
    # ) as mock_tpu_cluster_resolver:
    #     # with patch.object(
    #     #     # "wandb.sdk.internal.tpu.tpu_cluster_resolver.client",
    #     #     # "_get_tpu_utilization",
    #     #     # return_value="10",
    #     # ):
    #     # mock_tpu_cluster_resolver.return_value.TPUClusterResolver.return_value.get_master.return_value = (
    #     #     "grpc://1.2.3.4:847"
    #     # )
    #     # with patch.object(
    #     #     wandb.sdk.internal.tpu,
    #     #     "get_profiler",
    #     #     new_callable=mock__tpu_profiler,
    #     # ):
    #     with patch(
    #         "wandb.sdk.internal.tpu.TPUProfiler",
    #         new_callable=MockTPUProfiler,
    #     ):
    run = wandb.init(settings=test_settings)
    wandb.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())
    events = ctx_util.events[0]

    captured = capsys.readouterr()
    assert "Error initializing TPUProfiler" not in captured
    # assert "system.tpu" in events and events["system.tpu"] == 10
