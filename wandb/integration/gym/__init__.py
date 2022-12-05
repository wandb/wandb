import re
from typing import Optional

import wandb

_gym_version_lt_0_26: Optional[bool] = None


def monitor():
    vcr = wandb.util.get_module(
        "gym.wrappers.monitoring.video_recorder",
        required="Couldn't import the gym python package, install with `pip install gym`",
    )

    global _gym_version_lt_0_26

    if _gym_version_lt_0_26 is None:
        import gym  # type: ignore
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
        m = re.match(r".+(video\.\d+).+", getattr(self, path))
        if m:
            key = m.group(1)
        else:
            key = "videos"
        wandb.log({key: wandb.Video(getattr(self, path))})

    def del_(self):
        self.orig_close()

    if not _gym_version_lt_0_26:
        recorder.__del__ = del_
    recorder.close = close
    wandb.patched["gym"].append(
        [
            f"gym.wrappers.monitoring.video_recorder.{vcr_recorder_attribute}",
            "close",
        ]
    )
