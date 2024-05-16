import threading
import time

from google.cloud import storage
from wandb.sdk.internal.settings_static import SettingsStatic

# from wandb.sdk.internal.system.assets import Network
from wandb.sdk.internal.system.assets.network import (
    Network,
    NetworkTrafficReceived,
    NetworkTrafficSent,
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
    time.sleep(1)
    network_traffic_sent.clear()
    network_traffic_sent.sample()
    print(network_traffic_sent.samples)


def test_network_traffic_received():
    network_traffic_received = NetworkTrafficReceived()

    storage_client = storage.Client.create_anonymous_client()
    bucket = storage_client.bucket("public-raph-bucket")
    blob = bucket.blob("images")
    blob.download_to_filename("images.jpg")

    network_traffic_received.clear()
    network_traffic_received.sample()
    print(network_traffic_received.samples)
    print(network_traffic_received.last_sample)
