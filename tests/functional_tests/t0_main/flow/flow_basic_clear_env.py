import os

import wandb

# Clear network buffer setting (if set)
# this is temporary until we add an option in yea to allow this
os.environ.pop("WANDB__NETWORK_BUFFER", None)

run = wandb.init()

for x in range(10):
    run.log(dict(a=x))
