import wandb
import re


def monitor():
    vcr = wandb.util.get_module("gym.wrappers.monitoring.video_recorder",
                                required="Couldn't import the gym python package, install with pip install gym")
    vcr.ImageEncoder.orig_close = vcr.ImageEncoder.close

    def close(self):
        vcr.ImageEncoder.orig_close(self)
        m = re.match(r'.+(video\.\d+).+', self.output_path)
        if m:
            key = m.group(1)
        else:
            key = "videos"
        wandb.log({key: wandb.Video(self.output_path)})
    vcr.ImageEncoder.close = close
    wandb.patched["gym"].append(["gym.wrappers.monitoring.video_recorder.ImageEncoder", "close"])
