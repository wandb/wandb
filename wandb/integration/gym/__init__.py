import re

import wandb


def monitor():
    vcr = wandb.util.get_module(
        "gym.wrappers.monitoring.video_recorder",
        required="Couldn't import the gym python package, install with pip install gym",
    )
    vcr.VideoRecorder.orig_close = vcr.VideoRecorder.close

    def close(self):
        vcr.VideoRecorder.orig_close(self)
        m = re.match(r".+(video\.\d+).+", self.path)
        if m:
            key = m.group(1)
        else:
            key = "videos"
        wandb.log({key: wandb.Video(self.path)})

    def del_(self):
        self.orig_close()

    vcr.VideoRecorder.__del__ = del_
    vcr.VideoRecorder.close = close
    wandb.patched["gym"].append(
        ["gym.wrappers.monitoring.video_recorder.VideoRecorder", "close"]
    )
