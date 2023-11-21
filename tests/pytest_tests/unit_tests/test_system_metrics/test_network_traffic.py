import threading
import time
from typing import Tuple
from unittest import mock

import wandb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import Network

from wandb.sdk.internal.system.assets.network import (
    NetworkTrafficSent,
    NetworkTrafficReceived,
)
from wandb.sdk.internal.system.system_monitor import AssetInterface


def test_network_metrics(test_settings):
    interface = AssetInterface()
    settings = SettingsStatic(
        test_settings(
            dict(
                _stats_sample_rate_seconds=0.1,
                _stats_samples_to_average=2,
            )
        ).to_proto()
    )
    shutdown_event = threading.Event()

    network = Network(
        interface=interface, settings=settings, shutdown_event=shutdown_event
    )

    assert network.is_available()


def test_network_traffic_sent():
    network_traffic_sent = NetworkTrafficSent()
    network_traffic_sent.clear()
    network_traffic_sent.sample()
    print(network_traffic_sent.samples)
