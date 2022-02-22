import os

import wandb

os.environ["WANDB_TRACELOG"] = "logger"

run = wandb.init()
run.log(dict(acc=1))
run.finish()
