import copy
import json
import sys
import threading
import time
from unittest import mock

if sys.version_info >= (3, 8):
    from typing import get_args
else:
    from typing_extensions import get_args

import wandb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import GPUAMD
from wandb.sdk.internal.system.assets.gpu_amd import _StatsKeys
from wandb.sdk.internal.system.system_monitor import AssetInterface

STATS_AMD = {
    "card0": {
        "GPU ID": "0x740f",
        "Unique ID": "0x43cc8cc8af246708",
        "VBIOS version": "113-D67301-063",
        "Temperature (Sensor edge) (C)": "33.0",
        "Temperature (Sensor junction) (C)": "35.0",
        "Temperature (Sensor memory) (C)": "46.0",
        "Temperature (Sensor HBM 0) (C)": "46.0",
        "Temperature (Sensor HBM 1) (C)": "46.0",
        "Temperature (Sensor HBM 2) (C)": "45.0",
        "Temperature (Sensor HBM 3) (C)": "45.0",
        "fclk clock speed:": "(400Mhz)",
        "fclk clock level:": "0",
        "mclk clock speed:": "(1600Mhz)",
        "mclk clock level:": "3",
        "sclk clock speed:": "(800Mhz)",
        "sclk clock level:": "1",
        "socclk clock speed:": "(1090Mhz)",
        "socclk clock level:": "3",
        "Performance Level": "auto",
        "GPU OverDrive value (%)": "0",
        "GPU Memory OverDrive value (%)": "0",
        "Max Graphics Package Power (W)": "300.0",
        "Average Graphics Package Power (W)": "41.0",
        "GPU use (%)": "0",
        "GFX Activity": "3485543173",
        "GPU memory use (%)": "0",
        "Memory Activity": "312543105",
        "GPU memory vendor": "hynix",
        "PCIe Replay Count": "0",
        "Serial Number": "00000000000000",
        "Voltage (mV)": "793",
        "PCI Bus": "0000:63:00.0",
        "ASD firmware version": "0x00000000",
        "CE firmware version": "0",
        "DMCU firmware version": "0",
        "MC firmware version": "0",
        "ME firmware version": "0",
        "MEC firmware version": "70",
        "MEC2 firmware version": "70",
        "PFP firmware version": "0",
        "RLC firmware version": "17",
        "RLC SRLC firmware version": "0",
        "RLC SRLG firmware version": "0",
        "RLC SRLS firmware version": "0",
        "SDMA firmware version": "8",
        "SDMA2 firmware version": "8",
        "SMC firmware version": "00.68.56.00",
        "SOS firmware version": "0x0027007f",
        "TA RAS firmware version": "27.00.01.60",
        "TA XGMI firmware version": "32.00.00.13",
        "UVD firmware version": "0x00000000",
        "VCE firmware version": "0x00000000",
        "VCN firmware version": "0x0110101b",
        "Card series": "GENERIC RM IMAGE",
        "Card model": "0x0c34",
        "Card vendor": "Advanced Micro Devices, Inc. [AMD/ATI]",
        "Card SKU": "D67301",
        "Valid sclk range": "500Mhz - 1700Mhz",
        "Valid mclk range": "400Mhz - 1600Mhz",
        "Voltage point 0": "0Mhz 0mV",
        "Voltage point 1": "0Mhz 0mV",
        "Voltage point 2": "0Mhz 0mV",
        "Energy counter": "6122129286992",
        "Accumulated Energy (uJ)": "93668579258681.1",
    },
    "system": {"Driver version": "5.18.13"},
}


def test_gpu_amd(test_settings):
    with mock.patch.object(
        wandb.sdk.internal.system.assets.gpu_amd.subprocess,
        "check_output",
        return_value=json.dumps(STATS_AMD),
    ), mock.patch.object(
        wandb.sdk.internal.system.assets.gpu_amd.shutil,
        "which",
        return_value=True,
    ):
        # print(wandb.sdk.internal.system.assets.gpu_amd.get_rocm_smi_stats())

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

        gpu = GPUAMD(
            interface=interface,
            settings=settings,
            shutdown_event=shutdown_event,
        )
        gpu.is_available = lambda: True
        assert gpu.is_available()
        gpu.start()
        probe = gpu.probe()
        assert probe["gpu_count"] == 1
        assert (
            probe["gpu_devices"][0]["vendor"]
            == "Advanced Micro Devices, Inc. [AMD/ATI]"
        )
        time.sleep(1)
        shutdown_event.set()
        gpu.finish()

        assert not interface.metrics_queue.empty()

        metrics = interface.metrics_queue.get()

        known_metric_keys = list(get_args(_StatsKeys))
        assert all(f"gpu.0.{key}" in metrics for key in known_metric_keys)


def test_gpu_amd_missing_keys(test_settings):
    stats_amd_missing_keys = copy.deepcopy(STATS_AMD)
    stats_amd_missing_keys["card0"].pop("GPU use (%)")

    with mock.patch.object(
        wandb.sdk.internal.system.assets.gpu_amd.subprocess,
        "check_output",
        return_value=json.dumps(stats_amd_missing_keys),
    ), mock.patch.object(
        wandb.sdk.internal.system.assets.gpu_amd.shutil,
        "which",
        return_value=True,
    ):
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

        gpu = GPUAMD(
            interface=interface,
            settings=settings,
            shutdown_event=shutdown_event,
        )
        gpu.is_available = lambda: True
        gpu.start()
        time.sleep(1)
        shutdown_event.set()
        gpu.finish()

        assert not interface.metrics_queue.empty()
        metrics = interface.metrics_queue.get()

        assert "gpu.0.gpu" not in metrics

        known_metric_keys = [k for k in get_args(_StatsKeys) if k != "gpu"]
        assert all(f"gpu.0.{key}" in metrics for key in known_metric_keys)
