import re
import sys
from typing import Optional

import wandb
import wandb.util

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


_gym_version_lt_0_26: Optional[bool] = None
_required_error_msg = (
    "Couldn't import the gymnasium python package, "
    "install with `pip install gymnasium`"
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

    vcr = wandb.util.get_module(
        f"{gym_lib}.wrappers.monitoring.video_recorder",
        required=_required_error_msg,
    )

    global _gym_version_lt_0_26

    if _gym_version_lt_0_26 is None:
        if gym_lib == "gym":
            import gym
        else:
            import gymnasium as gym  # type: ignore
        from pkg_resources import parse_version

        if parse_version(gym.__version__) < parse_version("0.26.0"):
            _gym_version_lt_0_26 = True
        else:
            _gym_version_lt_0_26 = False

    # breaking change in gym 0.26.0
    vcr_recorder_attribute = "ImageEncoder" if _gym_version_lt_0_26 else "VideoRecorder"
    recorder = getattr(vcr, vcr_recorder_attribute)
    path = "output_path" if _gym_version_lt_0_26 else "path"

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
    wandb.patched["gym"].append(
        [
            f"{gym_lib}.wrappers.monitoring.video_recorder.{vcr_recorder_attribute}",
            "close",
        ]
    )
