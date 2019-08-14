import wandb
import re


def patch():
    vcr = wandb.util.get_module("gym.wrappers.monitoring.video_recorder",
                                required="Couldn't import the gym python package, install with pip install gym")
    vcr.ImageEncoder.orig_close = vcr.ImageEncoder.close

    def close(self):
        vcr.ImageEncoder.orig_close(self)
        m = re.match(r'.+(video\.\d+).+', self.output_path)
        if m:
            key = m[1]
        else:
            key = "videos"
        wandb.log({key: wandb.Video(self.output_path)})
    vcr.ImageEncoder.close = close
