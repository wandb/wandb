import itertools
import json
import threading
import time
from unittest import mock

import pytest
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import OpenMetrics

# from wandb.sdk.internal.system.assets.trainium import NeuronCoreStats
from wandb.sdk.internal.system.assets.interfaces import Asset
from wandb.sdk.internal.system.system_monitor import AssetInterface


def test_dcgm(test_settings):
    # with mock.patch.multiple(
    #     "wandb.sdk.internal.system.assets.trainium.NeuronCoreStats",
    #     neuron_monitor=neuron_monitor_mock,
    #     _is_matching_entry=_is_matching_entry_mock,
    # ):
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
    #
    # # wait for the mock data to be processed indefinitely,
    # # until the test times out in the worst case
    # while interface.metrics_queue.empty():
    #     time.sleep(0.1)
    #
    shutdown_event.set()
    dcgm.finish()

    # assert not interface.metrics_queue.empty()
    # assert not interface.telemetry_queue.empty()
