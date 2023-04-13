import random
import time
from typing import Union
from unittest import mock

import pytest
import wandb


def random_in_range(vmin: Union[int, float] = 0, vmax: Union[int, float] = 100):
    return random.random() * (vmax - vmin) + vmin


FAKE_METRICS = """# HELP DCGM_FI_DEV_MEM_COPY_UTIL Memory utilization (in %).
# TYPE DCGM_FI_DEV_MEM_COPY_UTIL gauge
DCGM_FI_DEV_MEM_COPY_UTIL{{gpu="0",UUID="GPU-c601d117-58ff-cd30-ae20-529ab192ba51",device="nvidia0",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="",namespace="",pod=""}} {gpu_0_memory_utilization}
DCGM_FI_DEV_MEM_COPY_UTIL{{gpu="1",UUID="GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e",device="nvidia1",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="dcgm-loadtest",namespace="default",pod="dcgm-loadtest"}} {gpu_1_memory_utilization}
# HELP DCGM_FI_DEV_GPU_TEMP GPU temperature (in C)
# TYPE DCGM_FI_DEV_GPU_TEMP gauge
DCGM_FI_DEV_GPU_TEMP{{gpu="0",UUID="GPU-c601d117-58ff-cd30-ae20-529ab192ba51",device="nvidia0",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="",namespace="",pod=""}} {gpu_0_temperature_c}
DCGM_FI_DEV_GPU_TEMP{{gpu="1",UUID="GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e",device="nvidia1",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="dcgm-loadtest",namespace="default",pod="dcgm-loadtest"}} {gpu_1_temperature_c}
# HELP DCGM_FI_DEV_POWER_USAGE Power draw (in W).
# TYPE DCGM_FI_DEV_POWER_USAGE gauge
DCGM_FI_DEV_POWER_USAGE{{gpu="0",UUID="GPU-c601d117-58ff-cd30-ae20-529ab192ba51",device="nvidia0",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="",namespace="",pod=""}} {gpu_0_power_draw_w}
DCGM_FI_DEV_POWER_USAGE{{gpu="1",UUID="GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e",device="nvidia1",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="dcgm-loadtest",namespace="default",pod="dcgm-loadtest"}} {gpu_1_power_draw_w}
"""


def random_metrics():
    return FAKE_METRICS.format(
        gpu_0_memory_utilization=random_in_range(),
        gpu_1_memory_utilization=random_in_range(),
        gpu_0_temperature_c=random_in_range(0, 100),
        gpu_1_temperature_c=random_in_range(0, 100),
        gpu_0_power_draw_w=random_in_range(0, 250),
        gpu_1_power_draw_w=random_in_range(0, 250),
    )


def mocked_requests_get(*args, **kwargs):
    return mock.Mock(
        status_code=200,
        text=random_metrics(),
    )


@pytest.mark.parametrize(
    "filters, expected_keys, unexpected_keys",
    [
        (
            (
                "node1.DCGM_FI_DEV_GPU_TEMP",
                "node2.DCGM_FI_DEV_MEM_COPY_UTIL",
            ),
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.1",
            ),
            (
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.0",
            ),
        ),
        (
            (".*DCGM_FI_DEV_(GPU_TEMP|MEM_COPY_UTIL)",),
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.1",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.1",
            ),
            (),
        ),
        (
            None,
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.1",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.1",
            ),
            (),
        ),
        (
            ".*",
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.1",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.1",
            ),
            (),
        ),
        (
            {
                ".*DCGM_FI_DEV_(GPU_TEMP|MEM_COPY_UTIL)": {"gpu": "0"},
            },
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.0",
            ),
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.1",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.1",
            ),
        ),
        (
            {
                ".*DCGM_FI_DEV_(GPU_TEMP|MEM_COPY_UTIL)": {"gpu": ".*"},
            },
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.0",
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node1.DCGM_FI_DEV_MEM_COPY_UTIL.1",
                "system.openmetrics.node2.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.1",
            ),
            (),
        ),
        (
            {
                "node1.DCGM_FI_DEV_GPU_TEMP": {"gpu": "0"},
                "node2.DCGM_FI_DEV_MEM_COPY_UTIL": {"gpu": "1"},
            },
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.0",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.0",
            ),
            # note: ".0" is just an index for the frontend, and not the GPU ID,
            # so we don't expect to see any ".1" metrics.
            # we do test the filtering logic in unit tests
            (
                "system.openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.1",
                "system.openmetrics.node2.DCGM_FI_DEV_MEM_COPY_UTIL.1",
            ),
        ),
    ],
)
def test_dcgm(
    wandb_init, relay_server, test_settings, filters, expected_keys, unexpected_keys
):
    with mock.patch.object(
        wandb.sdk.internal.system.assets.open_metrics.requests.Session,
        "get",
        mocked_requests_get,
    ), relay_server() as relay:
        run = wandb_init(
            project="stability",
            settings=test_settings(
                dict(
                    _stats_sample_rate_seconds=1,
                    _stats_samples_to_average=1,
                    # listen to the same endpoint for both "nodes"
                    _stats_open_metrics_endpoints={
                        "node1": "http://localhost:9400/metrics",
                        "node2": "http://localhost:9400/metrics",
                    },
                    _stats_open_metrics_filters=filters,
                )
            ),
        )

        # Wait for the first metrics to be logged
        # If there's an issue, the test will eventually time out and fail
        i = 0
        while not len(relay.context.get_file_contents("wandb-events.jsonl")):
            run.log({"junk": i})
            time.sleep(1)
            i += 1
        run.finish()

        logged_system_metric_keys = relay.context.events.columns.values

        assert all(key in logged_system_metric_keys for key in expected_keys)
        assert all(key not in logged_system_metric_keys for key in unexpected_keys)
