import random
import threading
import time
from typing import Union
from unittest import mock

import pytest
import requests
import wandb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import OpenMetrics
from wandb.sdk.internal.system.assets.interfaces import Asset
from wandb.sdk.internal.system.assets.open_metrics import (
    _nested_dict_to_tuple,
    _should_capture_metric,
)
from wandb.sdk.internal.system.system_monitor import AssetInterface


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


def mocked_requests_get_timeout(*args, **kwargs):
    raise requests.exceptions.ReadTimeout("Read Timeout")


def mocked_requests_get_junk(*args, **kwargs):
    return mock.Mock(
        status_code=200,
        text="CANNOTPARSETHISJUNK",
    )


def mocked_requests_get_retryable_error(*args, **kwargs):
    # return a HTTPError
    raise requests.exceptions.HTTPError(
        "HTTP Error 429: Too Many Requests",
        response=mock.Mock(
            status_code=429,
            text="",
        ),
    )


def mocked_requests_get_non_retryable_error(*args, **kwargs):
    # return a HTTPError
    raise requests.exceptions.HTTPError(
        "HTTP Error 404: Not Found",
        response=mock.Mock(
            status_code=404,
            text="",
        ),
    )


@pytest.mark.parametrize(
    "mocked_requests_get_method",
    [
        mocked_requests_get_junk,
        mocked_requests_get_retryable_error,
        mocked_requests_get_non_retryable_error,
    ],
)
def test_dcgm_not_available(test_settings, mocked_requests_get_method):
    with mock.patch.object(
        wandb.sdk.internal.system.assets.open_metrics.requests.Session,
        "get",
        mocked_requests_get_method,
    ):
        url = "http://localhost:9400/metrics"

        assert not OpenMetrics.is_available(url)


def test_endpoint_hang(test_settings):
    with mock.patch.object(
        wandb.sdk.internal.system.assets.open_metrics.requests.Session,
        "get",
        mocked_requests_get_timeout,
    ):
        url = "http://localhost:9400/metrics"
        assert not OpenMetrics.is_available(url)


def test_dcgm(test_settings):
    with mock.patch.object(
        wandb.sdk.internal.system.assets.open_metrics.requests.Session,
        "get",
        mocked_requests_get,
    ):
        interface = AssetInterface()
        settings = SettingsStatic(
            test_settings(
                dict(
                    _stats_sample_rate_seconds=1,
                    _stats_samples_to_average=1,
                )
            ).make_static()
        )
        shutdown_event = threading.Event()

        url = "http://localhost:9400/metrics"

        dcgm = OpenMetrics(
            interface=interface,
            settings=settings,
            shutdown_event=shutdown_event,
            name="dcgm",
            url=url,
        )

        assert dcgm.is_available(url)
        assert isinstance(dcgm, Asset)

        dcgm.start()

        # wait for the mock data to be processed indefinitely,
        # until the test times out in the worst case
        while interface.metrics_queue.empty():
            time.sleep(0.1)

        shutdown_event.set()
        dcgm.finish()

        assert not interface.metrics_queue.empty()
        assert not interface.telemetry_queue.empty()

        while not interface.metrics_queue.empty():
            print(interface.metrics_queue.get())


@pytest.mark.parametrize(
    "filters,endpoint_name,metric_name,metric_labels,should_capture",
    [
        (
            {".*DCGM_FI_DEV_POWER_USAGE": {"pod": "wandb-.*"}},
            "node1",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "wandb-1337"},
            True,
        ),
        (
            {".*DCGM_FI_DEV_POWER_USAGE": {"pod": "wandb-.*"}},
            "node2",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "not-wandb-1337"},
            False,
        ),
        (
            {".*DCGM_FI_DEV_POWER_USAGE": {"pod": "wandb-.*"}},
            "node3",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "wandb-1337", "container": "wandb"},
            True,
        ),
        (
            {".*DCGM_.*": {}},
            "node4",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "wandb-1337", "container": "not-wandb"},
            True,
        ),
        (
            {".*": {}},
            "node5",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "wandb-1337", "container": "not-wandb"},
            True,
        ),
        (
            {".*DCGM_.*": {"pod": "wandb-.*"}},
            "node6",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "wandb-1337"},
            True,
        ),
        (
            {".*DCGM_.*": {"pod": "wandb-.*"}},
            "node7",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "not-wandb-1337"},
            False,
        ),
        (
            {"node[0-9].DCGM_.*": {"pod": "wandb-.*"}},
            "node8",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "wandb-1337"},
            True,
        ),
        (
            {"node[0-7].DCGM_.*": {"pod": "wandb-.*"}},
            "node8",
            "DCGM_FI_DEV_POWER_USAGE",
            {"pod": "wandb-1337"},
            False,
        ),
    ],
)
def test_metric_filters(
    filters, endpoint_name, metric_name, metric_labels, should_capture
):
    assert (
        _should_capture_metric(
            endpoint_name,
            metric_name,
            tuple(metric_labels.items()),
            _nested_dict_to_tuple(filters),
        )
        is should_capture
    )
