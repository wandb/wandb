import re
import sys
from typing import Literal, Optional

import wandb
import wandb.util

_gym_version_lt_0_26: Optional[bool] = None
_gymnasium_version_lt_1_0_0: Optional[bool] = None

_required_error_msg = (
    "Couldn't import the gymnasium python package, install with `pip install gymnasium`"
)
GymLib = Literal["gym", "gymnasium"]


def monitor():
    """Monitor a gym environment.

    Supports both gym and gymnasium.
    """
    gym_lib: Optional[GymLib] = None

    # gym is not maintained anymore, gymnasium is the drop-in replacement - prefer it
    if wandb.util.get_module("gymnasium") is not None:
        gym_lib = "gymnasium"
    elif wandb.util.get_module("gym") is not None:
        gym_lib = "gym"

    if gym_lib is None:
        raise wandb.Error(_required_error_msg)

    global _gym_version_lt_0_26
    global _gymnasium_version_lt_1_0_0

    if _gym_version_lt_0_26 is None or _gymnasium_version_lt_1_0_0 is None:
        if gym_lib == "gym":
            import gym
        else:
            import gymnasium as gym  # type: ignore

        from packaging.version import parse

        gym_lib_version = parse(gym.__version__)
        _gym_version_lt_0_26 = gym_lib_version < parse("0.26.0")
        _gymnasium_version_lt_1_0_0 = gym_lib_version < parse("1.0.0a1")

    path = "path"  # Default path
    if gym_lib == "gymnasium" and not _gymnasium_version_lt_1_0_0:
        vcr_recorder_attribute = "RecordVideo"
        wrappers = wandb.util.get_module(
            f"{gym_lib}.wrappers",
            required=_required_error_msg,
        )
        recorder = getattr(wrappers, vcr_recorder_attribute)
    else:
        vcr = wandb.util.get_module(
            f"{gym_lib}.wrappers.monitoring.video_recorder",
            required=_required_error_msg,
        )
        # Breaking change in gym 0.26.0
        if _gym_version_lt_0_26:
            vcr_recorder_attribute = "ImageEncoder"
            recorder = getattr(vcr, vcr_recorder_attribute)
            path = "output_path"  # Override path for older gym versions
        else:
            vcr_recorder_attribute = "VideoRecorder"
            recorder = getattr(vcr, vcr_recorder_attribute)

    recorder.orig_close = recorder.close

    def close(self):
        recorder.orig_close(self)
        if not self.enabled:
            return
        if wandb.run:
            m = re.match(r".+(video\.\d+).+", getattr(self, path))
            key = m.group(1) if m else "videos"
            wandb.log({key: wandb.Video(getattr(self, path))})

    def del_(self):
        self.orig_close()

    if not _gym_version_lt_0_26:
        recorder.__del__ = del_
    recorder.close = close

    if gym_lib == "gymnasium" and not _gymnasium_version_lt_1_0_0:
        wrapper_name = vcr_recorder_attribute
    else:
        wrapper_name = f"monitoring.video_recorder.{vcr_recorder_attribute}"

    wandb.patched["gym"].append(
        [
            f"{gym_lib}.wrappers.{wrapper_name}",
            "close",
        ]
    )
