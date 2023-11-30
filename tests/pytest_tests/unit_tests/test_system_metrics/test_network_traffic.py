import threading
import time

from google.cloud import storage
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import Network
from wandb.sdk.internal.system.assets.network import NetworkTrafficSent
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
    time.sleep(1)
    network_traffic_sent.clear()
    network_traffic_sent.sample()
    print(network_traffic_sent.samples)
    print(network_traffic_sent.last_sample)
