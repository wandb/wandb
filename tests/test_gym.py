import wandb
from .utils import git_repo
from gym import core
from gym.wrappers.monitoring.video_recorder import ImageEncoder


def test_patch(wandb_init_run, git_repo):
    wandb.gym.monitor()
    with open("test.gif", "w") as f:
        f.write("test")
    ir = ImageEncoder("test.gif", (28, 28, 3), 10)
    ir.close()
    assert wandb_init_run.summary["videos"]['_type'] == "video-file"
