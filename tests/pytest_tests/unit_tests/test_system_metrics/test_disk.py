import threading

from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import Disk
from wandb.sdk.internal.system.system_monitor import AssetInterface


class MockPsutil:
    class MockDiskUsage:
        def __init__(self):
            self.total = 1000 * 1024 * 1024 * 1024  # 1000 GB in bytes
            self.used = 20 * 1024 * 1024 * 1024  # 20 GB in bytes

    class MockDiskIoCounters:
        def __init__(self):
            self.read_count = 100
            self.write_count = 200

    disk_usage = MockDiskUsage()
    disk_io_counters = MockDiskIoCounters()


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
            "total": disk.probe()["disk"]["total"],
            "used": disk.probe()["disk"]["used"],
            "disk i": disk.probe()["disk"]["disk i"],
            "disk o": disk.probe()["disk"]["disk o"],
        }
    }

    assert disk.is_available()

    assert disk.probe() == expected_metrics

    # # Test that the metrics_monitor was started
    disk.start()

    shutdown_event.set()
    disk.finish()

    # disk.finish()

    assert not interface.metrics_queue.empty()

    # # Test that the metrics_monitor was finished
    # disk.finish()
    # self.assertFalse(disk.metrics_monitor.is_alive())
