import wandb
import numpy as np
from tensorboardX import SummaryWriter

wandb.init(tensorboard=True)

writer = SummaryWriter()

writer.add_video("video", np.random.random(size=(1, 5, 3, 28, 28)))

wandb.log({"acc": 1})
