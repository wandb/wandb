import threading

import pytest
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import Disk
from wandb.sdk.internal.system.assets.disk import DiskIn, DiskOut
from wandb.sdk.internal.system.system_monitor import AssetInterface


@pytest.mark.skip(reason="This test is flaky")
def test_disk_metrics(test_settings):
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

    disk = Disk(interface=interface, settings=settings, shutdown_event=shutdown_event)

    # Test that the probe() method returns the correct disk metrics
    expected_metrics = {
        "disk": {
            "/": {
                "total": disk.probe()["disk"]["/"]["total"],
                "used": disk.probe()["disk"]["/"]["used"],
            }
        }
    }

    assert disk.is_available()

    assert disk.probe() == expected_metrics

    # Test that the metrics_monitor was started & finished
    disk.start()

    shutdown_event.set()

    disk.finish()

    assert not interface.metrics_queue.empty()


def test_disk_in():
    disk_in = DiskIn()
    disk_in.sample()
    assert len(disk_in.samples) == 1


def test_disk_out():
    disk_out = DiskOut()
    disk_out.sample()
    assert len(disk_out.samples) == 1
